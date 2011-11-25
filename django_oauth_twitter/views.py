from urllib2 import HTTPError

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import get_callable, NoReverseMatch, reverse
from django.conf.urls.defaults import patterns, url
from django.db import IntegrityError
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.utils.translation import ugettext_lazy as _

try:
    from django.utils.decorators import method_decorator
except ImportError:
    login_required_m = login_required
else:
    login_required_m = method_decorator(login_required)

from django_oauth_twitter.forms import RegistrationForm
from django_oauth_twitter.middleware import (cached_user_info,
                                             get_success_url,
                                             remove_tokens,
                                             set_access_token,
                                             set_request_token)
from django_oauth_twitter.models import (TwitterUser, TwitterAlreadyLinked,
                                         UserAlreadyLinked)
from django_oauth_twitter.signals import (twitter_user_associated,
                                          twitter_user_unassociated)
from django_oauth_twitter.utils import (fail_whale, login_redirect_url,
                                        next_url, TwitterApi, update_qs)

from oauth.oauth import OAuthToken


class OAuthTwitter(object):
    """Views for django-oauth-twitter."""
    def __init__(self,
                 auto_create_user=False,
                 registration_form=RegistrationForm,
                 association_url=None,
                 registration_url=None):
        """
        If `auto_create_user` is True, attempt to create a user automatically
        without signing up.

        `registration_form` is the form to use to create a new user.

        If `association_url` is a reverse()able string or view function,
        redirect to that view when associating a TwitterUser to a User.

        If `registration_url` is a reverse()able string or view function,
        redirect to that view in order to let a user register for a new
        User account.
        """
        self.auto_create_user = auto_create_user
        self._association_url_default = association_url is None
        if self._association_url_default:
            self.association_url = LazyReverse(self.associate)
        else:
            self.association_url = LazyReverse(association_url)
        if registration_url is None:
            self.registration_url = LazyReverse(self.register)
        else:
            self.registration_url = LazyReverse(registration_url)
        self.RegistrationForm = registration_form

    def get_urls(self):
        """
        Returns urlpatterns for urls.py.

        Include it like so::
            oauthtwitter = OAuthTwitter()
            urlpatterns += patterns('',
                url(r'^twitter/', include(oauthtwitter.urls)),
            )
        """
        urlpatterns = patterns('',
            url(r'^callback/', self.callback, name='twitter_callback'),
            url(r'^signin/', self.signin, name='twitter_signin'),
        )
        if self._association_url_default:
            # Add ^associate/ location if we're meant to handle association.
            urlpatterns += patterns('',
                url(r'^associate/signin/', self.signin,
                    kwargs={'success_url': 'twitter_associate'},
                    name='twitter_signin_associate'),
                url(r'^associate/', self.associate,
                    name='twitter_associate'),
            )
        if self.registration_url.location == self.register:
            # Add ^register/ location if we're meant to handle registration.
            urlpatterns += patterns('',
                url(r'^register/', self.registration_url.location,
                    name='twitter_register')
            )
        return urlpatterns
    urls = property(get_urls)

    @login_required_m
    def associate(self, request,
                  template="django_oauth_twitter/associate.html",
                  dictionary=None):
        """
        View to manage the association between a User and Twitter.

        `template` is the template to render for this webpage.

        If `dictionary` is provided, it provides extra context for
        rendering `template`.
        """
        if not request.user.is_authenticated():
            return self._redirect_to_login(request)
        if request.method == 'POST':
            if request.POST.get('action') == 'remove':
                twitter_id = request.POST.get('twitter_id')
                response = self._remove_association(request, twitter_id)
                if response:
                    return response
        self._check_for_revocation(request)
        if dictionary is None:
            dictionary = {}
        dictionary.update({'error': request.GET.get('error'),
                           'error_user': request.GET.get('user')})
        return render_to_response(template, dictionary=dictionary,
                                  context_instance=RequestContext(request))

    def callback(self, request):
        """
        View that gets the oauth_token from Twitter and signs in a User.

        Note: You must set this callback URL in Twitter's Application
        Details page.  Twitter ignores OAuth's oauth_callback option.
        """
        # Ensure that the user came in through signin().
        request_token = request.twitter_request_token
        if request_token is None:
            return self._redirect_to_login(request=request)
        # Ensure that the session's token matches Twitter's token.
        if request_token.key != request.GET.get('oauth_token'):
            remove_tokens(request)
            return self._redirect_to_login(request=request)
        # Save the access token in the session.
        api = TwitterApi(request_token)
        try:        
            access_token = fail_whale(api.getAccessToken)()
        except HTTPError, e:
            if e.code == 401:
                # Restart the authentication process, as Twitter thinks
                # we're unauthorized.
                return HttpResponseRedirect(reverse('twitter_signin'))
            raise
        set_access_token(request, access_token)
        # Funnel the user into the site.
        userinfo = cached_user_info(request, access_token)
        if request.user.is_anonymous():
            # Find the User by the access token.
            user = self._authenticate(userinfo=userinfo)
            if user is None:
                # New user
                return self._on_new_user(request=request)
            return self._login_and_redirect(request=request, user=user)
        return self._add_association(request, access_token)

    def signin(self, request, success_url=None):
        """
        View that redirects a user to the Twitter authorization page.

        `success_url` is a URL that the User will be redirected to, if
        they authorize Twitter OAuth.  If None, then defaults to
        settings.LOGIN_REDIRECT_URLNAME or LOGIN_REDIRECT_URL.
        """
        if success_url is None:
            success_url = next_url(request)
        else:
            success_url = str(LazyReverse(success_url))
        # Get a request token.
        twitter = TwitterApi()
        request_token = fail_whale(twitter.getRequestToken)()
        # Save success_url, along with the request token, in the session.
        set_request_token(request, request_token, success_url)
        # Redirect to Twitter's sign in URL.
        url = fail_whale(twitter.getSigninURL)(request_token)
        return HttpResponseRedirect(url)

    def register(self, request,
                 template='django_oauth_twitter/register.html',
                 dictionary=None,
                 no_thanks_url=settings.LOGOUT_URL):
        """
        View for registering a new user who has signed in with Twitter.

        `template` is the template to render for this webpage.

        If `dictionary` is provided, it provides extra context for
        rendering `template`.

        `no_thanks_url` is a URL for users who decide to cancel
        registration.
        """
        # Non-anonymous users can't sign up
        if request.user.is_anonymous():
            # Ensure that the user has an access token.
            access_token = request.twitter_access_token
            if access_token is None:
                return self._redirect_to_login(request=request)
            userinfo = request.twitter_userinfo
            screen_name = userinfo.screen_name
            if request.method == "POST":
                # Register the user
                form = self.RegistrationForm(request.POST,
                                             access_token=access_token,
                                             userinfo=userinfo)
                if form.is_valid():
                    user = form.save()
                    return self._login_and_redirect(request=request,
                                                    user=user)
            else:
                # Pre-fill with the user's Twitter screen name
                form = self.RegistrationForm(initial={'username': screen_name})
            if dictionary is None:
                dictionary = {}
            dictionary.update({'form': form,
                               'no_thanks': no_thanks_url,
                               'screen_name': screen_name})
            return render_to_response(template, dictionary=dictionary,
                                      context_instance=RequestContext(request))
        return self._redirect_to_home(request=request)

    def _authenticate(self, userinfo):
        """
        Returns user if `userinfo` is associated with a known user.
        Otherwise, returns None.
        """
        if userinfo is None:
            return None
        try:
            user = TwitterUser.objects.get(twitter_id=userinfo.id).user
        except TwitterUser.DoesNotExist:
            return None
        return user

    def _check_for_revocation(self, request):
        """
        Checks to see if `request.user` has revoked Twitter OAuth.

        If the TwitterUser has been revoked by Twitter, _unassociate()
        the credentials we have on file.
        """
        try:
            twitter_user = request.user.twitter
        except TwitterUser.DoesNotExist:
            pass
        else:
            if twitter_user.is_revoked():
                self._unassociate(request, raw=True)

    def _create_user(self, request):
        """
        Creates a User from their Twitter account and redirects to `url`.

        Afterwards, `login_and_redirect` to `url`.
        """
        user = None
        if request.user.is_anonymous():
            # Create the User
            access_token = request.twitter_access_token
            userinfo = request.twitter_userinfo
            form = self.RegistrationForm({'username': userinfo.screen_name},
                                         access_token=access_token,
                                         userinfo=userinfo)
            if form.is_valid():
                user = form.save()
            else:
                return HttpResponseRedirect(self.registration_url)
        # Login and redirect
        return self._login_and_redirect(request=request, user=user)

    def _login(self, request, user):
        # Nasty but necessary - annotate user and pretend it was the regular
        # auth backend. This is needed so django.contrib.auth.get_user works:
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)

    def _login_and_redirect(self, request, user):
        """
        Login `user` with `access_token` and redirects to `success_url`.

        `success_url` was the URL provided to OAuthTwitter.signin().

        If the `request.user` is already logged in, don't clobber the
        login with `user`.  The `request.user` has to log out first.
        """
        if user is None:
            return self._redirect_to_login(request=request)
        if request.user.is_anonymous():
            # Login
            self._login(request, user)
            # Update the access_token
            twitter = user.twitter
            save = False
            if twitter.update_access_token(request.twitter_access_token):
                save = True
            if twitter.update_userinfo(request.twitter_userinfo):
                save = True
            if save:
                twitter.save()
            # Redirect
            success_url = get_success_url(request)
            if success_url is not None:
                return HttpResponseRedirect(success_url)
        return self._redirect_to_home(request=request)

    def _on_new_user(self, request):
        """
        Handles an AnonymousUser who has just authenticated with Twitter.

        If `self.auto_create_user` is True, creates a new User with a
        username matching their Twitter screen name.  Otherwise,
        redirects the user into the registration process.
        """
        if self.auto_create_user:
            return self._create_user(request)
        return HttpResponseRedirect(self.registration_url)

    def _redirect_to_login(self, request):
        """Redirect to settings.LOGIN_URL."""
        return HttpResponseRedirect(settings.LOGIN_URL)

    def _redirect_to_home(self, request):
        """Redirect to settings.LOGIN_REDIRECT_URL."""
        return HttpResponseRedirect(login_redirect_url())

    def _add_association(self, request, access_token):
        """
        Adds an association for `access_token` to `request.user`.

        Returns an HttpResponse.
        """
        success_url = get_success_url(request=request)
        if success_url is None:
            success_url = login_redirect_url()
        try:
            self._associate(request, access_token)
        except UserAlreadyLinked:
            return HttpResponseRedirect(
                update_qs(success_url,
                          {'error': 'user_already_linked',
                           'user': request.user.username})
            )
        except TwitterAlreadyLinked:
            userinfo = cached_user_info(request, access_token)
            return HttpResponseRedirect(
                update_qs(success_url,
                          {'error': 'twitter_already_linked',
                           'user': userinfo.screen_name})
            )
        return HttpResponseRedirect(success_url)

    def _remove_association(self, request, twitter_id, fail_silently=True):
        """
        Removes the associated `twitter_id` from `request.user`.

        Returns None if there was no such TwitterUser associated with
        the User, unless `fail_silently` is False.

        Can return an HttpResponse to replace the one served by
        associate().
        """
        try:
            twitter_id = int(twitter_id)
        except TypeError, ValueError:
            if not fail_silently:
                raise
        user = request.user
        try:
            twitter_user = user.twitter
            if twitter_user.twitter_id == twitter_id:
                self._unassociate(request)
        except TwitterUser.DoesNotExist:
            if not fail_silently:
                raise

    def _associate(self, request, access_token):
        """Returns the TwitterUser just associated with `request.user`."""
        twitter_user = TwitterUser.objects.create_twitter_user(
            user=request.user,
            access_token=access_token,
            userinfo=cached_user_info(request, access_token)
        )
        twitter_user_associated.send(sender=self.__class__,
                                     twitter_user=twitter_user)
        return twitter_user

    def _unassociate(self, request, raw=False):
        """
        Unassociate a TwitterUser from a User and remove tokens from session.
        """
        user = request.user
        remove_tokens(request)
        try:
            screen_name = user.twitter.screen_name
            user.twitter.delete()
            del user._twitter_cache
            if not raw:
                twitter_user_unassociated.send(sender=self.__class__,
                                               user=user,
                                               screen_name=screen_name)
        except TwitterUser.DoesNotExist:
            pass


class LazyReverse(object):
    def __init__(self, location):
        self.location = location
        self.url = None

    def __str__(self):
        if callable(self.location) or '/' not in self.location:
            self.url = reverse(self.location)
        else:
            self.url = self.location
        return self.url
