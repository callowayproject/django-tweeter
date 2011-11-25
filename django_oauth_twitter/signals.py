from django.dispatch import Signal

# This signal is sent after a TwitterUser is created.
twitter_user_created = Signal(providing_args=['twitter_user'])

# These signals are sent after a TwitterUser has been associated or
# unassociated.
twitter_user_associated = Signal(providing_args=['twitter_user'])
twitter_user_unassociated = Signal(providing_args=['user', 'screen_name'])
