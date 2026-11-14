from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AddCash, Expense

GOOD_PW = 'Str0ng!Pass#2026'


def dt(delta=timedelta(0)):
    return (timezone.localtime() + delta).strftime('%Y-%m-%dT%H:%M')


class ManageCashFlowTests(TestCase):
    def test_register_login_and_transactions(self):
        r = self.client.post(reverse('register'), {
            'username': 'abin', 'email': 'abin@example.com',
            'password': GOOD_PW, 'confirm_password': 'nope'})
        self.assertContains(r, 'Passwords do not match')

        r = self.client.post(reverse('register'), {
            'username': 'abin', 'email': 'abin@example.com',
            'password': GOOD_PW, 'confirm_password': GOOD_PW})
        self.assertRedirects(r, reverse('dashboard'))
        self.client.post(reverse('logout'))

        r = self.client.post(reverse('login'), {'username': 'ABIN@example.com', 'password': GOOD_PW})
        self.assertRedirects(r, reverse('dashboard'))

        self.client.post(reverse('transaction_create', args=['income']), {
            'source': 'Salary', 'amount': '5000', 'datetime': dt(-timedelta(days=2)), 'description': 'Nov'})
        self.client.post(reverse('transaction_create', args=['expense']), {
            'description': 'Groceries', 'amount': '1200.50', 'datetime': dt(-timedelta(days=1))})
        self.assertEqual(AddCash.objects.count(), 1)
        self.assertEqual(Expense.objects.count(), 1)
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.context['balance'], Decimal('3799.50'))

        for name in ['transactions', 'profile']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

        e = Expense.objects.get()
        self.client.post(reverse('transaction_delete', args=['expense', e.pk]))
        self.assertEqual(Expense.objects.count(), 0)

    def test_users_cannot_touch_others_data(self):
        other = User.objects.create_user('other', password='x')
        cash = AddCash.objects.create(user=other, source='Gift', amount=10)
        User.objects.create_user('me', password=GOOD_PW)
        self.client.login(username='me', password=GOOD_PW)
        self.assertEqual(self.client.get(reverse('transaction_edit', args=['income', cash.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('transaction_delete', args=['income', cash.pk])).status_code, 404)
        self.assertTrue(AddCash.objects.filter(pk=cash.pk).exists())

    def test_login_required(self):
        r = self.client.get(reverse('dashboard'))
        self.assertRedirects(r, reverse('login') + '?next=/')


class RegistrationValidationTests(TestCase):
    url = reverse('register')

    def post(self, **over):
        data = {'username': 'abin_1554', 'email': 'abin@example.com',
                'password': GOOD_PW, 'confirm_password': GOOD_PW}
        data.update(over)
        return self.client.post(self.url, data)

    def assertFieldError(self, resp, field, text):
        self.assertEqual(resp.status_code, 200)
        errors = ' '.join(resp.context['form'].errors.get(field, []))
        self.assertIn(text, errors, msg=f'{field}: {errors}')
        self.assertFalse(User.objects.filter(username__iexact=resp.context['form'].data['username']).exists()
                         and field != 'username')

    def test_weak_passwords_rejected(self):
        self.assertFieldError(self.post(password='abc', confirm_password='abc'), 'password', 'too short')
        self.assertFieldError(self.post(password='password123', confirm_password='password123'), 'password', 'too common')
        self.assertFieldError(self.post(password='8273649182', confirm_password='8273649182'), 'password', 'entirely numeric')
        self.assertFieldError(self.post(password='abin_1554x', confirm_password='abin_1554x'), 'password', 'similar')

    def test_username_rules(self):
        self.assertFieldError(self.post(username='ab'), 'username', 'at least 3')
        self.assertFieldError(self.post(username='abin@x'), 'username', 'only contain')
        self.assertFieldError(self.post(username='ab in'), 'username', 'only contain')
        self.assertFieldError(self.post(username='12345'), 'username', 'at least one letter')
        self.assertFieldError(self.post(username='_abin'), 'username', 'cannot start or end')
        self.assertFieldError(self.post(username='Admin'), 'username', 'reserved')
        User.objects.create_user('Taken', email='t@example.com')
        self.assertFieldError(self.post(username='taken'), 'username', 'already taken')

    def test_email_rules(self):
        self.assertFieldError(self.post(email='not-an-email'), 'email', 'valid email')
        User.objects.create_user('someone', email='abin@example.com')
        self.assertFieldError(self.post(email='ABIN@Example.com'), 'email', 'already registered')

    def test_email_is_normalised(self):
        self.post(email='  Abin@Example.COM ')
        self.assertEqual(User.objects.get(username='abin_1554').email, 'abin@example.com')

    def test_error_banner_shown(self):
        r = self.post(username='')
        self.assertContains(r, 'Please fix the highlighted errors')


class LoginValidationTests(TestCase):
    def setUp(self):
        User.objects.create_user('Abin', email='abin@example.com', password=GOOD_PW)

    def test_case_insensitive_username_and_email(self):
        for ident in ['abin', 'ABIN', 'Abin@Example.com']:
            r = self.client.post(reverse('login'), {'username': ident, 'password': GOOD_PW})
            self.assertRedirects(r, reverse('dashboard'), msg_prefix=ident)
            self.client.post(reverse('logout'))

    def test_bad_credentials(self):
        r = self.client.post(reverse('login'), {'username': 'abin', 'password': 'wrong'})
        self.assertContains(r, 'Invalid username/email or password')
        r = self.client.post(reverse('login'), {'username': 'bad@', 'password': 'x'})
        self.assertContains(r, 'valid email address or username')

    def test_open_redirect_blocked(self):
        r = self.client.post(reverse('login') + '?next=https://evil.com/', {'username': 'abin', 'password': GOOD_PW})
        self.assertRedirects(r, reverse('dashboard'))


class ProfileValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('abin', email='abin@example.com', password=GOOD_PW)
        User.objects.create_user('other', email='other@example.com', password=GOOD_PW)
        self.client.force_login(self.user)

    def post(self, **over):
        data = {'username': 'abin', 'first_name': 'Mahmudul', 'last_name': 'Hasan',
                'email': 'abin@example.com', 'update_profile': '1'}
        data.update(over)
        return self.client.post(reverse('profile'), data)

    def errors(self, resp, field):
        return ' '.join(resp.context['profile_form'].errors.get(field, []))

    def test_valid_update(self):
        self.assertRedirects(self.post(first_name="  Abdul   Karim ", last_name="O'Neil-Rahman"), reverse('profile'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Abdul Karim')

    def test_email_required_and_unique(self):
        self.assertIn('required', self.errors(self.post(email=''), 'email'))
        self.assertIn('already registered', self.errors(self.post(email='OTHER@example.com'), 'email'))

    def test_username_unique_and_valid(self):
        self.assertIn('already taken', self.errors(self.post(username='Other'), 'username'))
        self.assertIn('only contain', self.errors(self.post(username='a b'), 'username'))

    def test_name_rules(self):
        self.assertIn('only contain letters', self.errors(self.post(first_name='Abin123'), 'first_name'))
        self.assertIn('at most 50', self.errors(self.post(last_name='A' * 51), 'last_name'))

    def test_bangla_name_allowed(self):
        self.assertRedirects(self.post(first_name='মাহমুদুল'), reverse('profile'))

    def test_invalid_post_does_not_leak_into_request_user(self):
        r = self.post(username='Other')
        self.assertEqual(r.context['user'].username, 'abin')

    def test_password_change_validation(self):
        r = self.client.post(reverse('profile'), {'old_password': 'wrong', 'new_password1': 'x',
                                                  'new_password2': 'y', 'change_password': '1'})
        self.assertTrue(r.context['password_form'].errors)
        r = self.client.post(reverse('profile'), {'old_password': GOOD_PW, 'new_password1': '12345678',
                                                  'new_password2': '12345678', 'change_password': '1'})
        self.assertIn('new_password2', r.context['password_form'].errors)


class TransactionValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('abin', email='abin@example.com', password=GOOD_PW)
        self.client.force_login(self.user)
        self.income = AddCash.objects.create(user=self.user, source='Salary', amount=Decimal('1000'),
                                             datetime=timezone.now() - timedelta(days=3))

    def add(self, kind, **over):
        data = ({'source': 'Freelance', 'description': ''} if kind == 'income' else {'description': 'Rent'})
        data.update({'amount': '100', 'datetime': dt(-timedelta(hours=1))})
        data.update(over)
        return self.client.post(reverse('transaction_create', args=[kind]), data)

    def err(self, resp, field):
        return ' '.join(resp.context['form'].errors.get(field, []))

    def test_amount_rules(self):
        self.assertIn('greater than zero', self.err(self.add('income', amount='0'), 'amount'))
        self.assertIn('greater than zero', self.err(self.add('income', amount='-5'), 'amount'))
        self.assertIn('Enter a number', self.err(self.add('income', amount='abc'), 'amount'))
        self.assertIn('2 decimal places', self.err(self.add('income', amount='10.555'), 'amount'))
        self.assertTrue(self.err(self.add('income', amount='99999999999'), 'amount'))
        self.assertEqual(AddCash.objects.count(), 1)

    def test_datetime_rules(self):
        self.assertIn('future', self.err(self.add('income', datetime=dt(timedelta(days=1))), 'datetime'))
        self.assertIn('2000', self.err(self.add('income', datetime='1999-12-31T10:00'), 'datetime'))
        self.assertIn('valid date', self.err(self.add('income', datetime='not-a-date'), 'datetime'))
        self.assertIn('required', self.err(self.add('income', datetime=''), 'datetime'))

    def test_current_local_time_accepted(self):
        self.assertRedirects(self.add('income', datetime=dt()), reverse('dashboard'))

    def test_text_rules(self):
        self.assertIn('at least one letter', self.err(self.add('income', source='12345'), 'source'))
        self.assertIn('at least 2', self.err(self.add('income', source='a'), 'source'))
        self.assertIn('required', self.err(self.add('income', source='   '), 'source'))
        self.assertIn('at least one letter', self.err(self.add('expense', description='!!!'), 'description'))
        self.assertTrue(self.err(self.add('income', description='x' * 501), 'description'))

    def test_whitespace_is_collapsed(self):
        self.add('income', source='  Part   time  job ')
        self.assertTrue(AddCash.objects.filter(source='Part time job').exists())

    def test_expense_cannot_exceed_balance(self):
        r = self.add('expense', amount='1000.01')
        self.assertIn('Insufficient balance', self.err(r, 'amount'))
        self.assertRedirects(self.add('expense', amount='1000'), reverse('dashboard'))

    def test_expense_edit_counts_its_own_amount(self):
        e = Expense.objects.create(user=self.user, description='Rent', amount=Decimal('800'))
        url = reverse('transaction_edit', args=['expense', e.pk])
        ok = self.client.post(url, {'description': 'Rent', 'amount': '1000', 'datetime': dt(-timedelta(hours=1))})
        self.assertRedirects(ok, reverse('transactions'))
        bad = self.client.post(url, {'description': 'Rent', 'amount': '1000.01', 'datetime': dt(-timedelta(hours=1))})
        self.assertIn('Insufficient balance', self.err(bad, 'amount'))

    def test_income_edit_and_delete_cannot_make_balance_negative(self):
        Expense.objects.create(user=self.user, description='Rent', amount=Decimal('600'))
        url = reverse('transaction_edit', args=['income', self.income.pk])
        r = self.client.post(url, {'source': 'Salary', 'amount': '500', 'datetime': dt(-timedelta(days=3))})
        self.assertIn('negative', self.err(r, 'amount'))
        self.client.post(reverse('transaction_delete', args=['income', self.income.pk]))
        self.assertTrue(AddCash.objects.filter(pk=self.income.pk).exists())

    @override_settings(MANAGECASH_ALLOW_NEGATIVE_BALANCE=True)
    def test_negative_balance_setting(self):
        self.assertRedirects(self.add('expense', amount='5000'), reverse('dashboard'))

    def test_unknown_kind_404(self):
        self.assertEqual(self.client.get('/transactions/loan/add/').status_code, 404)

    def test_delete_requires_post(self):
        r = self.client.get(reverse('transaction_delete', args=['income', self.income.pk]))
        self.assertEqual(r.status_code, 405)

    def test_bad_filter_falls_back_to_all(self):
        self.assertEqual(self.client.get(reverse('transactions') + '?type=<script>').status_code, 200)
        self.assertEqual(self.client.get(reverse('transactions_export_pdf') + '?type=xyz').status_code, 200)

    def test_db_constraint_blocks_non_positive_amount(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Expense.objects.create(user=self.user, description='Bad', amount=Decimal('-1'))
