from django import forms
from .models import IHG_Gateway, IHG_InboundConnector, IHG_OutboundConnector,IHG_MQTTConfiguration,Rule

class GatewayForm(forms.ModelForm):
    class Meta:
        model = IHG_Gateway
        fields = ['name', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows':2}),
        }

class InboundConnectorForm(forms.ModelForm):
    class Meta:
        model = IHG_InboundConnector
        fields = ['name', 'connector_id','connector_type','interval','maximum_data_points']
        

class OutboundConnectorForm(forms.ModelForm):
    class Meta:
        model = IHG_OutboundConnector
        fields = ['name', 'connector_type']
       
class MQTTConfigurationForm(forms.ModelForm):
    topics = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        help_text="Enter multiple topics separated by commas or new lines."
    )

    class Meta:
        model = IHG_MQTTConfiguration
        fields = ['broker_ip', 'port', 'username', 'password', 'interval']  # NO 'topics' here

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and hasattr(self.instance, 'topics'):
            existing_topics = self.instance.topics.all()
            self.initial['topics'] = ", ".join(t.name for t in existing_topics)

    def clean_topics(self):
        data = self.cleaned_data.get('topics')
        if not data:
            return []
        return [t.strip() for t in data.replace('\n', ',').split(',') if t.strip()]


from django import forms
from .models import Rule, IHG_InboundConnector
class RuleForm(forms.ModelForm):
    class Meta:
        model = Rule
        fields = ['name', 'stream', 'sql']
        widgets = {
            'sql': forms.Textarea(attrs={'rows': 6, 'cols': 80}),
        }

    def __init__(self, *args, **kwargs):
        gateway_id = kwargs.pop('gateway_id', None)
        super().__init__(*args, **kwargs)
        if gateway_id:
            self.fields['stream'].queryset = IHG_InboundConnector.objects.filter(gateway_id=gateway_id)
        else:
            self.fields['stream'].queryset = IHG_InboundConnector.objects.none()
