from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import AddCash, Expense


class ManageCashFlowTests(TestCase):
    def test_register_login_and_transactions(self):
        # Registration with mismatched passwords fails
        r = self.client.post(reverse('register'), {
            'username': 'abin', 'email': 'abin@example.com',
            'password': 'Secret123!', 'confirm_password': 'nope'})
        self.assertContains(r, 'Passwords do not match')

        # Successful registration logs user in
        r = self.client.post(reverse('register'), {
            'username': 'abin', 'email': 'abin@example.com',
            'password': 'Secret123!', 'confirm_password': 'Secret123!'})
        self.assertRedirects(r, reverse('dashboard'))
        self.client.post(reverse('logout'))

        # Login with email works
        r = self.client.post(reverse('login'), {'username': 'abin@example.com', 'password': 'Secret123!'})
        self.assertRedirects(r, reverse('dashboard'))

        # Add cash and expense
        self.client.post(reverse('transaction_create', args=['income']), {
            'source': 'Salary', 'amount': '5000', 'datetime': '2026-11-01T10:00', 'description': 'Nov'})
        self.client.post(reverse('transaction_create', args=['expense']), {
            'description': 'Groceries', 'amount': '1200.50', 'datetime': '2026-11-02T10:00'})
        self.assertEqual(AddCash.objects.count(), 1)
        self.assertEqual(Expense.objects.count(), 1)

        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.context['balance'], Decimal('3799.50'))
        self.assertContains(r, 'Groceries')

        # Pages render
        for name in ['transactions', 'profile']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

        # Delete expense
        e = Expense.objects.get()
        self.client.post(reverse('transaction_delete', args=['expense', e.pk]))
        self.assertEqual(Expense.objects.count(), 0)

    def test_users_cannot_touch_others_data(self):
        other = User.objects.create_user('other', password='x')
        cash = AddCash.objects.create(user=other, source='Gift', amount=10)
        User.objects.create_user('me', password='Secret123!')
        self.client.login(username='me', password='Secret123!')
        r = self.client.get(reverse('transaction_edit', args=['income', cash.pk]))
        self.assertEqual(r.status_code, 404)

    def test_login_required(self):
        r = self.client.get(reverse('dashboard'))
        self.assertRedirects(r, reverse('login') + '?next=/')
