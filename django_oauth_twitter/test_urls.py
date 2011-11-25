from django.conf.urls.defaults import *

from django_oauth_twitter.views import OAuthTwitter

oauthtwitter = OAuthTwitter()

def home(request):
    from django.http import HttpResponse
    return HttpResponse("")

urlpatterns = patterns('',
    url(r'^twitter/', include(oauthtwitter.urls)),
    url(r'^home/', home, name='home'),
    url(r'^logout/', 'django.contrib.auth.views.logout'),
)
