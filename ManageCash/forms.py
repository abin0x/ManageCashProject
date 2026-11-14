import re
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import password_validators_help_text_html, validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import AddCash, Expense, get_totals

# ---------------------------------------------------------------------------
# Limits & shared validators
# ---------------------------------------------------------------------------

USERNAME_MIN, USERNAME_MAX = 3, 30
USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]+$')
RESERVED_USERNAMES = {'admin', 'administrator', 'root', 'system', 'support', 'staff', 'managecash'}

MIN_AMOUNT = Decimal('0.01')
MAX_AMOUNT = Decimal('9999999999.99')      # fits the model's max_digits=12, decimal_places=2
EARLIEST_DATE = datetime(2000, 1, 1)
FUTURE_TOLERANCE = timedelta(minutes=5)    # small clock-skew allowance
NOTE_MAX = 500


def allow_negative_balance():
    return getattr(settings, 'MANAGECASH_ALLOW_NEGATIVE_BALANCE', False)


def clean_text(value, field_label, min_len=2):
    """Collapse whitespace and require at least one real letter."""
    value = ' '.join((value or '').split())
    if len(value) < min_len:
        raise ValidationError(f'{field_label} must be at least {min_len} characters.')
    if not any(ch.isalpha() for ch in value):
        raise ValidationError(f'{field_label} must contain at least one letter.')
    return value


def validate_username(username, exclude_pk=None):
    username = username.strip()
    # An existing user keeping their own username (e.g. the 'admin' superuser) is always allowed
    if exclude_pk and User.objects.filter(pk=exclude_pk, username=username).exists():
        return username
    if not USERNAME_MIN <= len(username) <= USERNAME_MAX:
        raise ValidationError(f'Username must be {USERNAME_MIN}-{USERNAME_MAX} characters long.')
    if not USERNAME_RE.match(username):
        raise ValidationError('Username can only contain English letters, numbers and _ . - (no spaces or @).')
    if not any(ch.isalpha() for ch in username):
        raise ValidationError('Username must contain at least one letter.')
    if username[0] in '.-_' or username[-1] in '.-_':
        raise ValidationError('Username cannot start or end with _ . or -')
    if username.lower() in RESERVED_USERNAMES:
        raise ValidationError('This username is reserved. Please choose another.')
    qs = User.objects.filter(username__iexact=username)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ValidationError('This username is already taken.')
    return username


def validate_unique_email(email, exclude_pk=None):
    email = email.strip().lower()
    qs = User.objects.filter(email__iexact=email)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ValidationError('This email is already registered.')
    return email


def validate_person_name(value, label):
    value = ' '.join((value or '').split())
    if not value:
        return value
    if len(value) > 50:
        raise ValidationError(f'{label} must be at most 50 characters.')
    # Letters in any script (incl. Bangla vowel signs, which are combining marks) plus space . ' -
    ok = all(ch.isalpha() or unicodedata.category(ch).startswith('M') or ch in " .'-" for ch in value)
    if not ok or not value[0].isalpha():
        raise ValidationError(f'{label} can only contain letters, spaces, dots, hyphens and apostrophes.')
    return value


# ---------------------------------------------------------------------------
# Auth forms
# ---------------------------------------------------------------------------

class RegistrationForm(forms.Form):
    username = forms.CharField(
        max_length=USERNAME_MAX, min_length=USERNAME_MIN,
        help_text=f'{USERNAME_MIN}-{USERNAME_MAX} characters: letters, numbers, _ . -',
        widget=forms.TextInput(attrs={'autocomplete': 'username', 'autofocus': True,
                                      'pattern': r'[A-Za-z0-9_.\-]{3,30}', 'placeholder': 'e.g. abin_1554'}))
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'placeholder': 'you@example.com'}))
    password = forms.CharField(
        strip=False, help_text=password_validators_help_text_html(),
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'minlength': 8}))
    confirm_password = forms.CharField(
        strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'minlength': 8}))

    def clean_username(self):
        return validate_username(self.cleaned_data['username'])

    def clean_email(self):
        return validate_unique_email(self.cleaned_data['email'])

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        confirm = cleaned.get('confirm_password')
        if password and confirm and password != confirm:
            self.add_error('confirm_password', 'Passwords do not match.')
        if password:
            # Run Django's AUTH_PASSWORD_VALIDATORS (length, common, numeric, similarity)
            candidate = User(username=cleaned.get('username', ''), email=cleaned.get('email', ''))
            try:
                validate_password(password, user=candidate)
            except ValidationError as e:
                self.add_error('password', e)
        return cleaned


class LoginForm(forms.Form):
    username = forms.CharField(
        label='Username or Email', max_length=254,
        widget=forms.TextInput(attrs={'autocomplete': 'username', 'autofocus': True}))
    password = forms.CharField(
        strip=False, max_length=128,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))

    def clean_username(self):
        value = self.cleaned_data['username'].strip()
        if '@' in value:
            try:
                forms.EmailField().clean(value)
            except ValidationError:
                raise ValidationError('Enter a valid email address or username.')
        return value


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'autocomplete': 'username', 'pattern': r'[A-Za-z0-9_.\-]{3,30}',
                                               'maxlength': USERNAME_MAX}),
            'first_name': forms.TextInput(attrs={'autocomplete': 'given-name', 'maxlength': 50}),
            'last_name': forms.TextInput(attrs={'autocomplete': 'family-name', 'maxlength': 50}),
            'email': forms.EmailInput(attrs={'autocomplete': 'email'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True          # needed for email login
        self.fields['username'].help_text = ''

    def clean_username(self):
        return validate_username(self.cleaned_data['username'], exclude_pk=self.instance.pk)

    def clean_email(self):
        return validate_unique_email(self.cleaned_data['email'], exclude_pk=self.instance.pk)

    def clean_first_name(self):
        return validate_person_name(self.cleaned_data['first_name'], 'First name')

    def clean_last_name(self):
        return validate_person_name(self.cleaned_data['last_name'], 'Last name')


# ---------------------------------------------------------------------------
# Transaction forms
# ---------------------------------------------------------------------------

def datetime_widget():
    return forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')


def amount_widget():
    return forms.NumberInput(attrs={'min': str(MIN_AMOUNT), 'max': str(MAX_AMOUNT), 'step': '0.01',
                                    'inputmode': 'decimal', 'placeholder': '0.00'})


class TransactionFormMixin:
    """Shared rules for income and expense forms. Pass user=request.user."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # previous amount when editing (needed for balance checks)
        self.original_amount = self.instance.amount if self.instance.pk else Decimal('0')
        now_local = timezone.localtime()
        self.fields['datetime'].widget.attrs.update({
            'min': EARLIEST_DATE.strftime('%Y-%m-%dT%H:%M'),
            'max': (now_local + FUTURE_TOLERANCE).strftime('%Y-%m-%dT%H:%M'),
        })
        self.fields['datetime'].label = 'Date & time'

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount is None:
            raise ValidationError('Amount is required.')
        if amount < MIN_AMOUNT:
            raise ValidationError('Amount must be greater than zero.')
        if amount > MAX_AMOUNT:
            raise ValidationError(f'Amount cannot be more than {MAX_AMOUNT:,}.')
        return amount

    def clean_datetime(self):
        value = self.cleaned_data['datetime']
        if value is None:
            raise ValidationError('Date & time is required.')
        if value > timezone.now() + FUTURE_TOLERANCE:
            raise ValidationError('Date & time cannot be in the future.')
        if value < timezone.make_aware(EARLIEST_DATE):
            raise ValidationError('Date must be on or after 1 Jan 2000.')
        return value

    def current_balance(self):
        return get_totals(self.user)[2] if self.user else Decimal('0')


class AddCashForm(TransactionFormMixin, forms.ModelForm):
    description = forms.CharField(
        required=False, max_length=NOTE_MAX, label='Note',
        help_text=f'Optional, up to {NOTE_MAX} characters.',
        widget=forms.Textarea(attrs={'rows': 3, 'maxlength': NOTE_MAX,
                                     'placeholder': 'Any extra details about this income'}))

    class Meta:
        model = AddCash
        fields = ['source', 'amount', 'datetime', 'description']
        labels = {'source': 'Source'}
        widgets = {
            'source': forms.TextInput(attrs={'placeholder': 'e.g. Salary, Freelance, Gift', 'minlength': 2}),
            'amount': amount_widget(),
            'datetime': datetime_widget(),
        }

    def clean_source(self):
        return clean_text(self.cleaned_data['source'], 'Source')

    def clean_description(self):
        return ' '.join((self.cleaned_data.get('description') or '').split())

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get('amount')
        # Lowering an existing income must not push the balance below zero
        if amount is not None and self.instance.pk and not allow_negative_balance():
            new_balance = self.current_balance() - self.original_amount + amount
            if new_balance < 0:
                self.add_error('amount', f'This change would make your balance negative '
                                         f'(৳ {new_balance:,.2f}). Minimum allowed: '
                                         f'৳ {self.original_amount - self.current_balance():,.2f}.')
        return cleaned


class ExpenseForm(TransactionFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['description', 'amount', 'datetime']
        labels = {'description': 'Description'}
        widgets = {
            'description': forms.TextInput(attrs={'placeholder': 'e.g. Groceries, Rent, Bus fare', 'minlength': 2}),
            'amount': amount_widget(),
            'datetime': datetime_widget(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user and not allow_negative_balance():
            available = max(self.current_balance() + self.original_amount, Decimal('0'))
            self.fields['amount'].help_text = f'Available balance: ৳ {available:,.2f}'

    def clean_description(self):
        return clean_text(self.cleaned_data['description'], 'Description')

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get('amount')
        if amount is not None and not allow_negative_balance():
            available = self.current_balance() + self.original_amount
            if amount > available:
                self.add_error('amount', f'Insufficient balance. You have ৳ {max(available, 0):,.2f} available.')
        return cleaned
