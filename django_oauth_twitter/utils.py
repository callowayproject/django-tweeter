from cgi import parse_qs
from urllib import urlencode
from urllib2 import HTTPError, URLError
from urlparse import urlsplit, urlunsplit

from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.urlresolvers import Resolver404, resolve, reverse
from django.utils.functional import update_wrapper


try:
    from oauthtwitter import OAuthApi
except AttributeError:
    # oauthtwitter has a nasty bug, where it imports oauth incorrectly.
    import oauth
    import oauth.oauth
    oauth.__dict__.update((k, v) for k, v in oauth.oauth.__dict__.iteritems()
                          if not (k.startswith('__') and k.endswith('__')))
    from oauthtwitter import OAuthApi


def TwitterApi(token=None):
    """
    Returns an OAuthApi object, given an optional `token`.
    """
    # Use the default consumer key and secret from settings.
    return OAuthApi(consumer_key=settings.TWITTER_CONSUMER_KEY,
                    consumer_secret=settings.TWITTER_CONSUMER_SECRET,
                    access_token=token)


def fail_whale(f):
    MAX_TRIES = 3
    def wrapper(*args, **kwargs):
        for tries in range(MAX_TRIES - 1):
            try:
                return f(*args, **kwargs)
            except HTTPError, e:
                if e.code != 503:
                    # Retry when Service Temporarily Unavailable
                    raise
            except URLError, e:
                errno = getattr(e.reason, 'args', [None])[0]
                if errno != 8:
                    # Retry when EOF occurred in violation of protocol
                    raise
        return f(*args, **kwargs)
    return update_wrapper(wrapper, f)

@fail_whale
def get_user_info(access_token):
    return TwitterApi(access_token).GetUserInfo()

def _host(netloc):
    return netloc.split(':')[0]

def next_url(request):
    import django.contrib.auth.views
    result = request.REQUEST.get(REDIRECT_FIELD_NAME, None)
    if result is None:
        # Use the default redirection.
        return login_redirect_url()
    elif _host(urlsplit(result).netloc) != _host(request.get_host()):
        # Ensure that the requested redirection is on this site.
        return login_redirect_url()
    else:
        # Ensure that we aren't sending the user to a useless page.
        try:
            view, args, kwargs = resolve(urlsplit(result).path)
            if view in [django.contrib.auth.views.logout]:
                return login_redirect_url()
        except Resolver404:
            pass
    return result

def login_redirect_url():
    """
    Returns the URL to redirect to, after a login.

    Prefers Pinax's settings.LOGIN_REDIRECT_URLNAME, but if that does
    not exist, falls back to Django's settings.LOGIN_REDIRECT_URL.
    """
    urlname = getattr(settings, 'LOGIN_REDIRECT_URLNAME', None)
    if urlname is not None:
        url = reverse(urlname)
    else:
        url = settings.LOGIN_REDIRECT_URL
    return url

def update_qs(url, dictionary):
    s, n, p, query, f = urlsplit(str(url))
    query_dict = parse_qs(query)
    query_dict.update(dictionary)
    return urlunsplit((s, n, p, urlencode(query_dict), f))
