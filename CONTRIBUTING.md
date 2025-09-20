## git

---

## **1. Commit Message Structure**

Always follow the format:

```
<type>(scope): <short summary>

<optional detailed description>

[Reference to issue/ticket]
```

Example:

```
feat(api): add product search endpoint

Implements a new GET /products/search endpoint with filtering and pagination.
Closes #123
```

---

## **2. Commit Types**

* **feat** → New feature
* **fix** → Bug fix
* **docs** → Documentation changes only
* **style** → Code style changes (formatting, no logic changes)
* **refactor** → Code restructuring without changing functionality or fixing a bug
* **perf** → Performance improvements
* **test** → Adding or updating tests
* **chore** → Maintenance tasks (dependencies, scripts, configs)
* **ci** → Continuous Integration or deployment config changes

---

## **3. Writing Rules**

* **Title ≤ 72 characters** → short and descriptive
* **Use imperative mood** (e.g., *add*, not *added* or *adds*)
* **No period at the end** of the title
* **Keep language consistent** (English for most open-source/commercial projects)
* **Avoid vague titles** like “update” or “fix bug” → be specific about *what* and *why*
* **Optional but recommended**: add a description to explain *why* and *how*
* **Reference** related issues/tickets (e.g., `#42`)

---

## **4. What to Avoid**

❌ “WIP” → use a dedicated branch instead
❌ “Misc changes” / “Update code” → not informative
❌ Cryptic messages → commits should be understandable without external context
❌ Moving important notes into code comments instead of the commit message

---

## **5. Examples of Good Commits**

```
fix(auth): prevent null pointer on login
feat(ui): add dark mode toggle in settings
refactor(cart): simplify price calculation logic
docs(readme): update setup instructions
```

---

💡 **Pro tip:** A good commit message is a **mini documentation entry** —
When reading history, you should understand *what* changed and *why*.

---

## **6. Branch Naming Standards**

* **Use descriptive names** that reflect the purpose of the branch.
* **Separate words with hyphens** (e.g., `feature/add-product-search`).
* **Prefix by type** when possible:
  - `feature/` for new features
  - `fix/` for bug fixes
  - `docs/` for documentation
  - `refactor/` for code refactoring
  - `test/` for tests
  - `chore/` for maintenance
* **Reference issue/ticket number** if relevant (e.g., `feature/123-add-product-search`).
* **Avoid generic names** like `dev`, `test`, or `wip`.

**Examples:**

```
feature/add-product-search
fix/login-null-pointer
docs/update-readme
refactor/cart-price-calculation
```

---

