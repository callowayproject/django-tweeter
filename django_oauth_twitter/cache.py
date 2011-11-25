"""
Provides Django caching for python-twitter and oauth-python-twitter modules.

By default, python-twitter and oauth-python-twitter use a filesystem
cache.  By using DjangoCachedApi to wrap these modules, you can take
advantage of the Django cache framework.

To use with python-twitter
--------------------------

* Install python-twitter
* Always wrap python-twitter's API with DjangoCachedApi:

    import twitter
    from cache import DjangoCachedApi

    api = DjangoCachedApi(api=twitter.Api())
    api.GetPublicTimeline()

To use with oauth-python-twitter
--------------------------------

* Install oauth-python-twitter
* Patch oauth-python-twitter with cache_fetchurl.patch from:
  http://code.google.com/p/oauth-python-twitter/issues/detail?id=9
* Always wrap oauth-python-twitter's API with DjangoCachedApi:

    import oauthtwitter
    from cache import DjangoCachedApi

    api = DjangoCachedApi(api=oauthtwitter.OAuthApi(consumer_key=KEY,
                                                    consumer_secret=SECRET,
                                                    access_token=token))
    api.GetPublicTimeline()
"""


from django.core.cache import cache


class DjangoCachedApi(object):
    """
    Wrapper around twitter.Api so it uses the Django cache framework.

        import twitter
        api = DjangoCachedApi(twitter.Api())
        api.GetPublicTimeline()
    """

    def __init__(self, api, cache_timeout=None, cache_backend=None):
        """
        Wrap twitter.Api so it uses the Django cache framework.

        `api` is an instance of twitter.Api.

        `cache_timeout` is the cache timeout, in seconds.  Defaults to
        the default cache timeout for `api`.

        `cache_backend` is the Django cache backend.  Defaults to
        Django's CACHE_BACKEND.
        """
        self.api = api
        if cache_timeout is None:
            cache_timeout = api._cache_timeout
        self.api.SetCache(DjangoCache(cache_timeout, cache_backend))

    def __getattr__(self, name):
        # Passthrough for attribute resolution to self.api
        return getattr(self.api, name)

    def __setattr__(self, name, value):
        # Passthrough for attribute resolution to self.api
        if name in self.__dict__ or name == 'api':
            # Let us set our own attributes
            return super(DjangoCachedApi, self).__setattr__(name, value)
        return setattr(self.api, name, value)

    def __delattr__(self, name):
        # Passthrough for attribute resolution to self.api
        if name in self.__dict__:
            # Let us delete our own attributes
            return super(DjangoCachedApi, self).__delattr__(name)
        return delattr(self.api, name)

    def SetCache(self, cache):
        # You are not allowed to set a new cache
        raise DjangoCacheError('DjangoCache cannot be replaced.')

    def SetCacheTimeout(self, cache_timeout):
        """
        Override the default cache timeout.

        `cache_timeout`: time, in seconds, that responses should be reused.
        """
        self.api._cache_timeout = cache_timeout
        self.api._cache.cache_timeout = cache_timeout


class DjangoCache(object):
    """Wrap the Django cache framework so it implements twitter._FileCache."""

    def __init__(self, cache_timeout, cache_backend=None):
        """
        Wraps the Django cache framework.

        `cache_timeout` is the cache timeout, in seconds.

        `cache_backend` is the Django cache backend.  Defaults to
        Django's CACHE_BACKEND.
        """
        self.cache_timeout = cache_timeout
        if cache_backend is None:
            self._cache = cache
        else:
            self._cache = cache_backend
        self._data = (None, None)

    def Get(self, key):
        """Returns the value of `key` from the cache, or None if missing."""
        cached_key, cached_value = self._data
        if key != cached_key:
            # `Get(key)` must always follow `GetCachedTime(key)`.
            raise DjangoCacheError('Key %s does not match %s. '
                                   'GetCachedTime() must be called first.' %
                                   (key, cached_key))
        return cached_value

    def Set(self, key, data):
        """Set the cached value of `key` as `data`."""
        return self._cache.set(key, data, self.cache_timeout)

    def Remove(self, key, data):
        """Removes the cached value of `key`."""
        return self._cache.delete(key)

    def GetCachedTime(self, key):
        """Returns infinity is `key` is in the cache.  -Infinity if missing."""
        value = self._cache.get(key)
        if value is None:
            self._data = (None, None)
            # Force _FetchUrl() to always compute a new result.
            return float('-inf')
        # `key` was found in cache and it is stored in `self._data` so
        # that `Get(key)` will return this result.  If this didn't
        # happen, there might be a race where _FetchUrl() will see
        # that the `key` is in the cache but it expired before it
        # could actually perform the `Get(key)`.
        self._data = (key, value)
        # Force _FetchUrl() to never compute a new result.
        return float('inf')


class DjangoCacheError(Exception):
    pass
