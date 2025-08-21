from django import forms
from .models import IHG_Gateway, IHG_InboundConnector, IHG_OutboundConnector,IHG_MQTTConfiguration

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
    class Meta:
        model = IHG_MQTTConfiguration
        fields = ['broker_ip', 'port', 'username', 'password', 'topic', 'interval']