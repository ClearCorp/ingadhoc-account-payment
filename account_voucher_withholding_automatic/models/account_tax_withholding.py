# -*- coding: utf-8 -*-
from openerp import models, fields, api
import openerp.addons.decimal_precision as dp
from dateutil.relativedelta import relativedelta
import datetime


class AccountTaxWithholding(models.Model):
    _inherit = "account.tax.withholding"
    _description = "Account Withholding Taxes"

    non_taxable_minimum = fields.Float(
        'Non-taxable Minimum',
        digits=dp.get_precision('Account'),
        )
    base_amount_type = fields.Selection([
        ('untaxed_amount', 'Untaxed Amount'),
        ('total_amount', 'Total Amount'),
        # neto gravado + no gravado / neto gravado / importe total
        # importe de iva?
        ],
        'Base Amount',
        help='Base amount used to get withholding amount',
        )
    advances_are_withholdable = fields.Boolean(
        'Advances are Withholdable?',
        default=True,
        )
    accumulated_payments = fields.Selection([
        ('month', 'Month'),
        ('year', 'Year'),
        ],
        string='Accumulated Payments',
        help='If none is selected, then payments are not accumulated',
        )
    # TODO implement
    # allow_modification = fields.Boolean(
    #     )
    type = fields.Selection([
        ('none', 'None'),
        ('percentage', 'Percentage'),
        # ('fixed', 'Fixed Amount'),
        # ('code', 'Python Code'), ('balance', 'Balance')
         ],
        'Type',
        required=True,
        default='none',
        help="The computation method for the tax amount."
        )
    amount = fields.Float(
        'Amount',
        digits=dp.get_precision('Account'),
        help="For taxes of type percentage, enter % ratio between 0-1."
        )

    @api.multi
    def create_voucher_withholdings(self, voucher):
        # for tax in self.filtered(lambda x: x.type == 'percentage'):
        for tax in self.filtered(lambda x: x.type != 'none'):
            voucher_withholding = self.env[
                'account.voucher.withholding'].search([
                    ('voucher_id', '=', voucher.id),
                    ('tax_withholding_id', '=', tax.id),
                    ('automatic', '=', True),
                    ], limit=1)
            vals = tax.get_withholding_vals(voucher)
            if not vals.get('amount'):
                continue
            # vals = {
            #     # 'amount': voucher.amount * tax.amount,
            #     'voucher_id': voucher.id,
            #     'tax_withholding_id': tax.id,
            #     'automatic': True,
            #         }
            if voucher_withholding:
                voucher_withholding.write(vals)
            else:
                voucher_withholding = voucher_withholding.create(vals)
            # voucher_withholding.get_withholding_data()
        return True

    # @api.multi
    # def get_non_taxable_minimum(self, voucher):
    #     self.ensure_one()
    #     return self.non_taxable_minimum

    @api.multi
    def get_withholdable_invoiced_amount(self, voucher):
        self.ensure_one()
        amount = 0.0
        for line in self.env['account.voucher.line'].search([
                ('voucher_id', '=', voucher.id)]):
            factor = self.get_withholdable_factor(line)
            sign = 1.0
            if voucher.type == 'payment':
                sign = -1.0
            if line.type == 'dr':
                sign = sign * -1.0
            amount += line.amount * sign * factor
        return amount

    @api.multi
    def get_withholdable_factor(self, voucher_line):
        self.ensure_one()
        factor = 1.0
        if self.base_amount_type == 'untaxed_amount':
            invoice = voucher_line.move_line_id.invoice
            factor = invoice.amount_untaxed / invoice.amount_total
        return factor

    @api.multi
    def get_withholding_vals(self, voucher):
        self.ensure_one()
        # voucher = self.voucher_id
        withholdable_invoiced_amount = self.get_withholdable_invoiced_amount(
            voucher)
        withholdable_advanced_amount = 0.0
        if self.advances_are_withholdable:
            withholdable_advanced_amount = voucher.advance_amount

        to_date = fields.Date.from_string(
            voucher.date) or datetime.date.today()
        accumulated_amount = previous_withholding_amount = 0.0
        accumulated_payments = self.accumulated_payments
        if accumulated_payments == 'month':
            previos_vouchers_domain = [
                ('partner_id', '=', voucher.partner_id.id),
                ('state', '=', 'posted'),
                ('id', '!=', voucher.id),
                ]
            if accumulated_payments == 'month':
                from_relative_delta = relativedelta(day=1)
            elif accumulated_payments == 'year':
                from_relative_delta = relativedelta(day=1, month=1)
            from_date = to_date + from_relative_delta
            previos_vouchers_domain += [
                ('date', '<=', to_date),
                ('date', '>=', from_date),
                ]
            same_period_vouchers = voucher.search(previos_vouchers_domain)
            accumulated_amount = sum(same_period_vouchers.mapped('amount'))
            previous_withholding_amount = sum(
                self.env['account.voucher.withholding'].search([
                    ('voucher_id', 'in', same_period_vouchers.ids),
                    ('tax_withholding_id', '=', self.id),
                    ]).mapped('amount'))

        total_amount = (
            accumulated_amount +
            withholdable_advanced_amount +
            withholdable_invoiced_amount)
        # non_taxable_minimum = self.get_non_taxable_minimum(voucher)
        non_taxable_minimum = self.non_taxable_minimum
        withholdable_base_amount = total_amount - non_taxable_minimum
        period_withholding_amount = withholdable_base_amount * self.amount
        # period_withholding_amount = self.get_period_withholding_amount(
        #     withholdable_base_amount, voucher)
        computed_withholding_amount = (
            period_withholding_amount - previous_withholding_amount)

        return {
            'withholdable_invoiced_amount': withholdable_invoiced_amount,
            'withholdable_advanced_amount': withholdable_advanced_amount,
            'accumulated_amount': accumulated_amount,
            'total_amount': total_amount,
            'non_taxable_minimum': non_taxable_minimum,
            'withholdable_base_amount': withholdable_base_amount,
            'period_withholding_amount': period_withholding_amount,
            'previous_withholding_amount': previous_withholding_amount,
            'computed_withholding_amount': computed_withholding_amount,
            'amount': computed_withholding_amount,
            'voucher_id': voucher.id,
            'tax_withholding_id': self.id,
            'automatic': True,
        }
        # self.withholdable_invoiced_amount = withholdable_invoiced_amount
        # self.accumulated_amount = accumulated_amount
        # self.total_amount = total_amount
        # self.non_taxable_minimum = non_taxable_minimum
        # self.withholdable_base_amount = withholdable_base_amount
        # self.period_withholding_amount = period_withholding_amount
        # # TODO, que este valor lo devuelva el tax
        # self.previous_withholding_amount = previous_withholding_amount
        # self.computed_withholding_amount
        # self.amount = computed_withholding_amount


# class account_tax_withholding_template(models.Model):
#     _inherit = "account.tax.withholding.template"
#     _inherit = "account.tax.withholding"
    # _description = "Account Withholding Taxes Template"