from django import forms


class PublicQuoteRequestForm(forms.Form):
    company_name = forms.CharField(label="Empresa", max_length=200)
    contact_name = forms.CharField(label="Nombre de contacto", max_length=160)
    email = forms.EmailField(label="Correo", max_length=254)
    phone = forms.CharField(label="Teléfono (opcional)", max_length=40, required=False)
    subject = forms.CharField(label="¿Qué servicio necesitas?", max_length=240)
    details = forms.CharField(label="Cuéntanos un poco más", max_length=5000, widget=forms.Textarea)
    consent = forms.BooleanField(label="Acepto que Redmagna use estos datos para responder a mi solicitud.")
    utm_source = forms.CharField(required=False, max_length=120, widget=forms.HiddenInput)
    utm_medium = forms.CharField(required=False, max_length=120, widget=forms.HiddenInput)
    utm_campaign = forms.CharField(required=False, max_length=120, widget=forms.HiddenInput)
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off", "aria-hidden": "true"}))

    def clean_company_name(self):
        return self.cleaned_data["company_name"].strip()

    def clean_contact_name(self):
        return self.cleaned_data["contact_name"].strip()

    def clean_phone(self):
        return self.cleaned_data["phone"].strip()

    def clean_subject(self):
        return self.cleaned_data["subject"].strip()

    def clean_details(self):
        return self.cleaned_data["details"].strip()

    def clean_utm_source(self):
        return self.cleaned_data["utm_source"].strip()

    def clean_utm_medium(self):
        return self.cleaned_data["utm_medium"].strip()

    def clean_utm_campaign(self):
        return self.cleaned_data["utm_campaign"].strip()
