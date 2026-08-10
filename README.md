## Restaurant POS (RPOS)

Restaurant POS built natively on the Frappe Framework / ERPNext v15.

The full specification lives in [`../docs`](../docs). Implementation follows
[`../docs/10_Implementation_Plan.md`](../docs/10_Implementation_Plan.md).

### Status

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Foundation — app structure, all DocTypes | DocTypes complete |
| 2 | Core order flow — APIs, Vue 3 POS, offline queue | Not started |
| 3 | Printing system | Not started |
| 4 | Advanced features | Not started |
| 5 | Testing & hardening | Not started |

### Installation

```bash
bench get-app restaurant_pos /path/to/ruzmh_pos/restaurant_pos
bench --site your-site install-app restaurant_pos
```

### License

MIT
