from django.contrib import admin

from django_oauth_twitter.models import TwitterUser

class TwitterUserAdmin(admin.ModelAdmin):
    list_display = ('user', 'twitter_id', 'screen_name')
    search_fields = ('user', 'twitter_id')
    ordering = ('user',)

admin.site.register(TwitterUser, TwitterUserAdmin)
