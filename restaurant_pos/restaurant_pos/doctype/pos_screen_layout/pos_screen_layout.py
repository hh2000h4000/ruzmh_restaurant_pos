# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class POSScreenLayout(Document):
	def validate(self):
		self.validate_grid()
		if self.is_grid and self.switched_to_grid():
			self.place_in_order()
		self.validate_buttons()

	def switched_to_grid(self) -> bool:
		"""Whether the buttons have never been placed on a grid (`D-295`).

		A layout built in `flow` has every button at column 1, row 1 — the
		defaults, never read there. Switching it to `grid` met the manager with
		«cell (1, 1) is already used by row 1» for a placement nobody made. So a
		layout arriving on the grid is laid out in the order of its table first;
		positions the manager sets after that are theirs and are checked.
		"""
		before = self.get_doc_before_save()
		if before is not None:
			return before.layout_mode != "grid"
		buttons = self.buttons or []
		return len(buttons) > 1 and all(
			cint(row.col_start) <= 1 and cint(row.row_start) <= 1 for row in buttons
		)

	def place_in_order(self):
		"""Each button in the first free cell, row by row, in the table's order."""
		columns, rows = cint(self.grid_columns), cint(self.grid_rows)
		taken: set[tuple[int, int]] = set()
		for button in self.buttons or []:
			wide, tall = max(cint(button.col_span), 1), max(cint(button.row_span), 1)
			spot = next(
				(
					(col, row)
					for row in range(1, rows - tall + 2)
					for col in range(1, columns - wide + 2)
					if not any(
						(c, r) in taken for c in range(col, col + wide) for r in range(row, row + tall)
					)
				),
				None,
			)
			if spot is None:
				frappe.throw(
					_("{0} buttons do not fit on a grid of {1} columns and {2} rows.").format(
						len(self.buttons), columns, rows
					)
				)
			button.col_start, button.row_start = spot
			taken.update(
				(c, r) for c in range(spot[0], spot[0] + wide) for r in range(spot[1], spot[1] + tall)
			)

	@property
	def is_grid(self) -> bool:
		"""Whether the coordinates on the buttons mean anything (`D-142`).

		In `flow` they do not: the till lays the buttons out in the order of the
		table below and never reads a column. So every rule about columns is off
		here — and it has to be, because the fields default to 1 and a manager
		adding a second row would otherwise be told it collides with the first,
		about a grid the form does not even show them.
		"""
		return self.layout_mode == "grid"

	def validate_grid(self):
		if not self.is_grid:
			return

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

			if self.is_grid:
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
