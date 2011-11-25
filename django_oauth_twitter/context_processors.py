from django.utils.functional import SimpleLazyObject

from twitter import User

def twitter_userinfo(request):
    twitter_userinfo = getattr(request, 'twitter_userinfo', '')
    if not twitter_userinfo:
        return {}
    return {'twitter_userinfo': twitter_userinfo}
