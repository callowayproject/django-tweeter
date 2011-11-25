from urllib2 import HTTPError

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.utils.translation import ugettext_lazy as _

from oauth.oauth import OAuthToken
import simplejson
import twitter

from django_oauth_twitter.cache import DjangoCachedApi
from django_oauth_twitter.signals import twitter_user_created
from django_oauth_twitter.utils import fail_whale, get_user_info, TwitterApi


class UserAlreadyLinked(Exception):
    pass


class TwitterAlreadyLinked(Exception):
    pass


class TwitterUserManager(models.Manager):
    @staticmethod
    def _access_token(access_token, userinfo=None):
        if userinfo is None:
            userinfo = get_user_info(access_token)
        attributes = {'access_token_str': str(access_token),
                      'twitter_id': userinfo.id,
                      'userinfo_json': userinfo.AsJsonString()}
        return (attributes, userinfo)

    def create_twitter_user(self, user, access_token, userinfo=None):
        """
        Returns a new TwitterUser from `user` and `access_token`.

        If `userinfo` is provided, it will use that instead of
        fetching recent Twitter user info using `access_token`.
        """
        attributes, userinfo = self._access_token(access_token, userinfo)
        if self.get_query_set().filter(user=user):
            raise UserAlreadyLinked('User %s is already linked to Twitter.' %
                                    user)
        if self.get_query_set().filter(access_token_str=access_token):
            raise TwitterAlreadyLinked('Twitter user %s is already linked.' %
                                       userinfo.screen_name)
        return self.create(user=user, **attributes)

    def update_or_create(self, user, access_token, userinfo=None):
        """
        Returns a (TwitterUser, created) tuple from `user` and `access_token`.

        `created` is True when the TwitterUser had to be created.

        If `userinfo` is provided, it will use that instead of
        fetching recent Twitter user info using `access_token`.
        """
        attributes, userinfo = self._access_token(access_token, userinfo)
        obj, created = self.get_or_create(user=user,
                                          defaults=attributes)
        if not created:
            save = False
            if obj.update_access_token(access_token):
                save = True
            if obj.update_userinfo(userinfo):
                save = True
            if save:
                obj.save()
        user._twitter_cache = obj
        return obj, created


class TwitterUser(models.Model):
    user = models.OneToOneField(User, unique=True, verbose_name=_('user'),
                                related_name='twitter')
    twitter_id = models.IntegerField(unique=True)
    access_token_str = models.TextField()
    userinfo_json = models.TextField(blank=True)
    objects = TwitterUserManager()

    def __init__(self, *args, **kwargs):
        super(TwitterUser, self).__init__(*args, **kwargs)
        self._api = None

    def __unicode__(self):
        return self.userinfo().screen_name

    @classmethod
    def on_create(cls, sender, instance, created, raw, **kwargs):
        if created and not raw:
            twitter_user_created.send(sender=cls, twitter_user=instance)

    def get_access_token(self):
        if self.access_token_str:
            return OAuthToken.from_string(self.access_token_str)
        return None

    def set_access_token(self, value):
        self.access_token_str = str(value)

    access_token = property(get_access_token, set_access_token)

    def update_access_token(self, access_token):
        if self.access_token != access_token:
            self.access_token = access_token
            return True

    def api(self):
        cache_timeout = getattr(settings, 'DJANGO_OAUTH_TWITTER_CACHE_TIMEOUT',
                                60)
        if self._api is None:
            self._api = DjangoCachedApi(api=TwitterApi(self.access_token),
                                        cache_timeout=cache_timeout)
        return self._api

    def is_revoked(self):
        try:
            # Use a non-cached API
            fail_whale(TwitterApi(self.access_token).GetUserInfo)()
        except HTTPError, e:
            if e.code == 401:
                return True
            raise
        else:
            return False

    def userinfo(self):
        if self.userinfo_json:
            userinfo_dict = simplejson.loads(self.userinfo_json)
            userinfo = twitter.User.NewFromJsonDict(userinfo_dict)
        else:
            userinfo = self.update_userinfo()
        return userinfo

    def update_userinfo(self, userinfo=None):
        if userinfo is None:
            userinfo = fail_whale(self.api().GetUserInfo)()
        userinfo_json = userinfo.AsJsonString()
        if self.userinfo_json != userinfo_json:
            self.userinfo_json = userinfo_json
            return userinfo

    def get_screen_name(self):
        return self.userinfo().screen_name

    screen_name = property(get_screen_name)

    def get_site_friends(self, user=None):
        """
        Returns a queryset of Users who are Twitter friends of `user`.

        If `user` is None, default to this User.
        """
        friends = fail_whale(self.api().GetFriends)(user=user, cursor=None)
        return self.__class__.objects.filter(
            twitter_id__in=[f.id for f in friends]
        )

    def get_site_followers(self):
        """Returns a queryset of Users who are Twitter followers of this User."""
        followers = fail_whale(self.api().GetFollowers)(cursor=None)
        return self.__class__.objects.filter(
            twitter_id__in=[f.id for f in followers]
        )

post_save.connect(TwitterUser.on_create, sender=TwitterUser)
