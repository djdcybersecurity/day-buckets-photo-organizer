Got it ✅ — here’s a clean `README.md` you can copy-paste directly:

````markdown
# 📸 DayBuckets – SDI-4233 Project

DayBuckets is a Python CLI utility that:

1. **Fetches** images + metadata from Wikimedia Commons.  
2. **Organizes** them into `YYYY/MM/DD` buckets based on timestamps.  
3. **Generates** a Markdown `report.md` and `manifest.json` summarizing the organized files.  

This project was completed for **SDI-4233: Memory Tools and Analysis**.  

---

## ⚙️ Requirements
- Python 3.10+
- Standard library only (no third-party dependencies)

---

## 🚀 How to Run

Clone the repository:
```bash
git clone https://github.com/<your-username>/day-buckets-photo-organizer-djdcybersecurity.git
cd day-buckets-photo-organizer-djdcybersecurity
````

Run the three pipeline steps in order:

### 1. Fetch Wikimedia Commons images

Downloads images and writes sidecar `.meta.json` files into `project/incoming/`.

```bash
python3 daybuckets.py fetch --category "Cathedrals" --dest ./project --limit 3 --verbose
```

### 2. Organize into date buckets

Moves or copies files into `project/buckets/YYYY/MM/DD/`.

```bash
python3 daybuckets.py organize --dest ./project --mode copy --verbose
```

### 3. Generate report and manifest

Builds a human-readable report (`report.md`) and machine-readable manifest (`manifest.json`).

```bash
python3 daybuckets.py report --dest ./project --verbose
```

---

## 📂 Example Output

### Buckets structure:

```
project/
  incoming/
  buckets/
    2025/
      09/
        18/
          example.jpg
          example.jpg.meta.json
  logs/
  report.md
  manifest.json
```

### Example `report.md`

```markdown
# DayBuckets Report

### 2025/09/18
- example.jpg
- example.jpg.meta.json
```

### Example `manifest.json`

```json
{
  "buckets": {
    "2025/09/18": [
      "example.jpg",
      "example.jpg.meta.json"
    ]
  }
}
```

---

## 🧑‍🏫 Testing Instructions (For Professor)

1. Clone repo and `cd` into it.
2. Run the 3 commands in order (`fetch`, `organize`, `report`).
3. Verify:

   * Images and `.meta.json` files are downloaded into `project/incoming/`.
   * Files are organized under `project/buckets/YYYY/MM/DD/`.
   * `report.md` contains a summary of all organized files.
   * `manifest.json` contains structured metadata.

**Dry-run testing**: Add `--dry-run` to any step to simulate actions without writing files.

---

## 📜 Notes

* Wikimedia Commons categories are case-sensitive.
* Example test category: `Cathedrals`.
* No external libraries required.

```

Do you also want me to generate a **sample `report.md` from your current buckets** so you can include it in the repo as proof-of-output, or leave the placeholder so your professor generates it fresh?
```
