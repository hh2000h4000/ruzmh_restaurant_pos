# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class POSScreenLayout(Document):
	def validate(self):
		self.validate_grid()
		self.validate_buttons()

	def validate_grid(self):
		if cint(self.grid_columns) < 1:
			frappe.throw(_("Grid Columns must be at least 1."))
		if cint(self.grid_rows) < 1:
			frappe.throw(_("Grid Rows must be at least 1."))

	def validate_buttons(self):
		occupied = {}
		reference_field = {
			"item_group": "item_group",
			"item": "item",
			"goto_screen": "goto_screen",
			"action": "action_type",
		}

		for row in self.buttons or []:
			fieldname = reference_field[row.button_type]
			if not row.get(fieldname):
				frappe.throw(
					_("Row #{0}: {1} is required for a '{2}' button.").format(
						row.idx, _(row.meta.get_label(fieldname)), row.button_type
					)
				)

			# Keep only the reference matching the button type.
			for button_type, other_field in reference_field.items():
				if button_type != row.button_type:
					row.set(other_field, None)

			if row.button_type == "goto_screen" and row.goto_screen == self.name:
				frappe.throw(_("Row #{0}: A button cannot navigate to its own screen.").format(row.idx))

			self.validate_button_geometry(row)
			self.validate_button_overlap(row, occupied)

	def validate_button_geometry(self, row):
		if cint(row.col_span) < 1 or cint(row.row_span) < 1:
			frappe.throw(_("Row #{0}: Column Span and Row Span must be at least 1.").format(row.idx))

		if cint(row.col_start) < 1 or cint(row.row_start) < 1:
			frappe.throw(_("Row #{0}: Column Start and Row Start are 1-based.").format(row.idx))

		if cint(row.col_start) + cint(row.col_span) - 1 > cint(self.grid_columns):
			frappe.throw(
				_("Row #{0}: Button exceeds the grid width of {1} columns.").format(
					row.idx, self.grid_columns
				)
			)

		if cint(row.row_start) + cint(row.row_span) - 1 > cint(self.grid_rows):
			frappe.throw(
				_("Row #{0}: Button exceeds the grid height of {1} rows.").format(row.idx, self.grid_rows)
			)

	def validate_button_overlap(self, row, occupied):
		for col in range(cint(row.col_start), cint(row.col_start) + cint(row.col_span)):
			for grid_row in range(cint(row.row_start), cint(row.row_start) + cint(row.row_span)):
				cell = (col, grid_row)
				if cell in occupied:
					frappe.throw(
						_("Row #{0}: Cell (column {1}, row {2}) is already used by row #{3}.").format(
							row.idx, col, grid_row, occupied[cell]
						)
					)
				occupied[cell] = row.idx
