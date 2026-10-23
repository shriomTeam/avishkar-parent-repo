# Shared UI

Import shared Tailwind components from `@clinic/ui`. The web app scans this
package in `app/globals.css`, which also defines the shared brand tokens.

Use `Panel`, `PageHeading`, `StatusBadge`, `Avatar`, and `buttonStyles` for
page structure and controls. `buttonStyles` lets a routing link look like a
button without nesting interactive elements.

Workspace overview components:

- `ProductGrid` provides responsive one-, two-, and three-column layouts.
- `ProductCard` accepts a title, description, icon, active status, and optional
  action slot. The host owns routes and access checks; the component has no
  dependency on feature packages or Next.js.
- `navigationItemStyles(active)` provides the shared workspace navigation style;
  the host owns links, active-route detection, and `aria-current`.

Platform Settings lives at `/settings`; platform sign-out is located there.
Feature settings pages remain owned by their respective feature packages.

`AccountMenu` provides the shared bottom profile disclosure (Settings and Sign
out), keyboard dismissal, outside-click dismissal, and focus handling. Pass an
`onSignOut` callback from the host's auth layer; shared UI does not import auth or
feature code. `Dialog placement="right"` renders an accessible side drawer with
the same focus restoration and Escape/backdrop behavior as centered dialogs.

Shared Settings uses these controls alongside existing `Tabs`, `TextField`,
`Dropdown`, `DataTable`, `Panel`, and `SidebarLayout` components.
