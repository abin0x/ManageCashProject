from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

AMOUNT_VALIDATORS = [MinValueValidator(Decimal('0.01')), MaxValueValidator(Decimal('9999999999.99'))]


class AddCash(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cash_entries')
    source = models.CharField(max_length=100)
    datetime = models.DateTimeField(default=timezone.now)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=AMOUNT_VALIDATORS)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['-datetime']
        verbose_name = 'Add Cash'
        verbose_name_plural = 'Add Cash'
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='addcash_amount_positive')]

    def __str__(self):
        return f'{self.user.username} +{self.amount} ({self.source})'


class Expense(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expenses')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=AMOUNT_VALIDATORS)
    datetime = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-datetime']
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='expense_amount_positive')]

    def __str__(self):
        return f'{self.user.username} -{self.amount} ({self.description})'


def get_totals(user):
    """Return (total_income, total_expense, balance) for a user."""
    income = AddCash.objects.filter(user=user).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    expense = Expense.objects.filter(user=user).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    return income, expense, income - expense
