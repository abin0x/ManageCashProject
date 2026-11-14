from itertools import chain

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (AddCashForm, ExpenseForm, LoginForm, ProfileForm, RegistrationForm,
                    allow_negative_balance)
from .models import AddCash, Expense, get_totals
from .pdf import build_transactions_pdf

FORM_ERROR_MSG = 'Please fix the highlighted errors and try again.'

# kind -> (form class, model, label)
TRANSACTION_TYPES = {
    'income': (AddCashForm, AddCash, 'Cash'),
    'expense': (ExpenseForm, Expense, 'Expense'),
}


def _get_type(kind):
    if kind not in TRANSACTION_TYPES:
        raise Http404('Unknown transaction type')
    return TRANSACTION_TYPES[kind]


_totals = get_totals


def _transactions(user):
    """Merge AddCash and Expense rows into one list, newest first."""
    cash = (
        {'kind': 'income', 'id': c.id, 'title': c.source, 'note': c.description,
         'amount': c.amount, 'datetime': c.datetime}
        for c in AddCash.objects.filter(user=user)
    )
    exp = (
        {'kind': 'expense', 'id': e.id, 'title': e.description, 'note': '',
         'amount': e.amount, 'datetime': e.datetime}
        for e in Expense.objects.filter(user=user)
    )
    return sorted(chain(cash, exp), key=lambda t: t['datetime'], reverse=True)


# ---------- Authentication ----------

def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
            )
            login(request, user)
            messages.success(request, 'Account created successfully. Welcome!')
            return redirect('dashboard')
        messages.error(request, FORM_ERROR_MSG)
    return render(request, 'ManageCash/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        identifier = form.cleaned_data['username']
        password = form.cleaned_data['password']
        # Accept either username or email (both case-insensitive)
        lookup = {'email__iexact': identifier} if '@' in identifier else {'username__iexact': identifier}
        match = User.objects.filter(**lookup).first()
        username = match.username if match else identifier
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            next_url = request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
                return redirect(next_url)
            return redirect('dashboard')
        messages.error(request, 'Invalid username/email or password.')
    return render(request, 'ManageCash/login.html', {'form': form})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('login')


# ---------- Dashboard & transactions ----------

@login_required
def dashboard(request):
    income, expense, balance = _totals(request.user)
    return render(request, 'ManageCash/dashboard.html', {
        'total_income': income,
        'total_expense': expense,
        'balance': balance,
        'recent': _transactions(request.user)[:10],
        'income_count': AddCash.objects.filter(user=request.user).count(),
        'expense_count': Expense.objects.filter(user=request.user).count(),
    })


@login_required
def transactions(request):
    kind = request.GET.get('type', 'all')
    items = _transactions(request.user)
    if kind in TRANSACTION_TYPES:
        items = [t for t in items if t['kind'] == kind]
    return render(request, 'ManageCash/transactions.html', {'items': items, 'kind': kind})


@login_required
def transactions_export_pdf(request):
    kind = request.GET.get('type', 'all')
    items = _transactions(request.user)
    if kind in TRANSACTION_TYPES:
        items = [t for t in items if t['kind'] == kind]
    else:
        kind = 'all'
    pdf = build_transactions_pdf(request.user, items, kind, _totals(request.user))
    filename = f'managecash-{kind}-{timezone.localdate():%Y-%m-%d}.pdf'
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def transaction_create(request, kind):
    form_class, _, label = _get_type(kind)
    form = form_class(request.POST or None, user=request.user)
    if request.method == 'POST':
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            messages.success(request, f'{label} saved successfully.')
            return redirect('dashboard')
        messages.error(request, FORM_ERROR_MSG)
    title = 'Add Cash' if kind == 'income' else 'Add Expense'
    return render(request, 'ManageCash/transaction_form.html',
                  {'form': form, 'title': title, 'kind': kind})


@login_required
def transaction_edit(request, kind, pk):
    form_class, model, label = _get_type(kind)
    obj = get_object_or_404(model, pk=pk, user=request.user)
    form = form_class(request.POST or None, instance=obj, user=request.user)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, f'{label} updated.')
            return redirect('transactions')
        messages.error(request, FORM_ERROR_MSG)
    return render(request, 'ManageCash/transaction_form.html',
                  {'form': form, 'title': f'Edit {label}', 'kind': kind, 'editing': True})


@login_required
@require_POST
def transaction_delete(request, kind, pk):
    _, model, label = _get_type(kind)
    obj = get_object_or_404(model, pk=pk, user=request.user)
    # Deleting income must not leave the balance negative
    if kind == 'income' and not allow_negative_balance():
        new_balance = _totals(request.user)[2] - obj.amount
        if new_balance < 0:
            messages.error(request, f'Cannot delete this income: your balance would become '
                                    f'৳ {new_balance:,.2f}. Delete or reduce some expenses first.')
            return redirect('transactions')
    obj.delete()
    messages.success(request, f'{label} deleted.')
    return redirect('transactions')


# ---------- Profile ----------

@login_required
def profile(request):
    profile_form = ProfileForm(instance=request.user)
    password_form = PasswordChangeForm(request.user)
    if request.method == 'POST':
        if 'update_profile' in request.POST:
            # Use a fresh copy: an invalid ModelForm still writes its values onto the
            # instance, which would otherwise leak into request.user (e.g. the sidebar).
            profile_form = ProfileForm(request.POST, instance=User.objects.get(pk=request.user.pk))
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Profile updated successfully.')
                return redirect('profile')
            messages.error(request, FORM_ERROR_MSG)
        elif 'change_password' in request.POST:
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Password changed successfully.')
                return redirect('profile')
            messages.error(request, FORM_ERROR_MSG)
    income, expense, balance = _totals(request.user)
    return render(request, 'ManageCash/profile.html', {
        'profile_form': profile_form,
        'password_form': password_form,
        'total_income': income,
        'total_expense': expense,
        'balance': balance,
    })
