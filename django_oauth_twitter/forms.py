from django.contrib.auth.models import User
from django.forms import ModelForm

from django_oauth_twitter.models import TwitterUser

class RegistrationForm(ModelForm):
    class Meta:
        model = User
        fields = ('username',)

    def __init__(self, *args, **kwargs):
        self.access_token = kwargs.pop('access_token', None)
        self.userinfo = kwargs.pop('userinfo', None)
        initial = kwargs.get('initial', None)
        if initial is not None and 'username' in initial:
            if User.objects.filter(username=initial['username']):
                # User already exists in the system, so don't prefill the
                # username.
                del initial['username']
        return super(RegistrationForm, self).__init__(*args, **kwargs)

    def save(self):
        user = super(RegistrationForm, self).save(commit=False)
        user.set_unusable_password()
        user.save()
        # Associate it with a Twitter account.
        TwitterUser.objects.update_or_create(user=user,
                                             access_token=self.access_token,
                                             userinfo=self.userinfo)
        return user
