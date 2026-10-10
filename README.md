## Restaurant POS (RPOS)

A restaurant point of sale built natively on the Frappe Framework / ERPNext v15:
a Vue 3 till, kitchen tickets and receipts, shifts and drawers, returns,
promotions, coupons, gift cards, loyalty points, and one aggregated posting to
the books when the day is closed.

### Requirements

- A working bench with **Frappe v15** and **ERPNext v15** installed on the site
- Python 3.10+
- Node 18+ and yarn (the till's screen is built on your machine)

### Installation

Run these from your bench folder (`cd ~/frappe-bench`), one after the other.
Replace `your-site` with the name of your site.

**1. Get the app**

```bash
bench get-app https://github.com/hh2000h4000/ruzmh_restaurant_pos.git
```

The repository is private: when asked, enter your GitHub username, and a
personal access token as the password.

**2. Install it on the site**

```bash
bench --site your-site install-app restaurant_pos
```

**3. Migrate**

```bash
bench --site your-site migrate
```

**4. Build the till's screen**

```bash
bench build --app restaurant_pos
```

**5. Restart**

```bash
bench restart
```

On a development bench, stop `bench start` and run it again instead.

### Optional: demo data

A small Arabic menu, production centres with printers, modifier groups, twelve
tables and a screen layout. Safe to run twice.

```bash
bench --site your-site execute restaurant_pos.setup.demo.create_demo_data
```

### First use

1. Open the desk and go to the **Restaurant POS** workspace.
2. Run **Quick Setup** (`/app/rpos-quick-setup`): it makes a branch, its
   sections and tables, and a cashier terminal from one form.
3. Open the till at **`/restaurant-pos`** and pair the device with the terminal.
4. The user guide, in Arabic, is at **`/rpos-guide`** (also under Help in the desk).

### Updating

```bash
cd apps/restaurant_pos && git pull && cd ../..
```

```bash
bench --site your-site migrate
```

```bash
bench build --app restaurant_pos
```

### Warnings

- **Do not run `bench run-tests` on a site that holds real data.** ERPNext's
  own test setup deletes every Item Price on the site it runs against.
- Quick Setup turns on **Allow Negative Stock** in Stock Settings, so a day's
  stock can post while a purchase is still unrecorded. Turn it off there if the
  shop records purchases as they arrive.

### License

MIT
