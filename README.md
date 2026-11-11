# ilias-sync

Ein Skill für [Claude Code](https://claude.com/claude-code), der das Kursmaterial eines Semesters von ILIAS herunterlädt und aufgeräumt in einen Ordner deiner Wahl legt, zum Beispiel in iCloud.

- Beim ersten Lauf fragt der Skill, welches Semester, welcher Zielordner und welche Kurse synchronisiert werden sollen. Danach lädt jeder Lauf nur noch, was neu ist.
- Der Login läuft automatisch über [agent-browser](https://github.com/vercel-labs/agent-browser), in einem eigenen Chrome ohne Fenster.
- Vorhandene Dateien werden nie überschrieben. Duplikate erkennt der Skill auch dann, wenn du Dateien umbenannt hast.

Gebaut und getestet für das ILIAS der FH Münster (ILIAS 10, Anmeldung über Shibboleth). Für ein anderes ILIAS lässt sich die Adresse einstellen, das ist aber ungetestet.

## Voraussetzungen

- macOS (Linux sollte gehen, ist aber ungetestet)
- Claude Code
- [uv](https://docs.astral.sh/uv/) für die Python-Abhängigkeiten: `brew install uv`
- Node.js für agent-browser: `npm install -g agent-browser && agent-browser install`

## Installation

```bash
git clone https://github.com/julian-krause/ilias-sync.git ~/.claude/skills/ilias-sync
```

Danach in Claude Code `/ilias-sync` eingeben.

## Erster Lauf: Einrichtung

Claude führt dich durch vier kurze Fragen:

1. **Zugangsdaten:** Claude öffnet die Datei `.env`, du trägst Kennung und Passwort ein. Wer das nicht möchte, meldet sich bei jedem Lauf selbst in einem Browserfenster an.
2. **Semester:** Auswahl aus deinen ILIAS-Kategorien, z. B. „Wintersemester 2026“.
3. **Zielordner:** frei wählbar.
4. **Kurse:** Du siehst alle Kurse des Semesters mit einem Vorschlag für kurze Ordnernamen und bestätigst, benennst um oder wählst ab.

Danach startet der erste Sync direkt.

Jeder weitere Aufruf von `/ilias-sync` synchronisiert genau die bestätigten Kurse, ohne Rückfragen. Trittst du in ILIAS einem neuen Kurs bei, fragt der Skill einmal nach, ob er dazukommen soll.

## Später ändern

Sag es Claude einfach: „Kurs X nicht mehr synchronisieren“, „Kurs Y dazunehmen“, „neues Semester einrichten“, „Zielordner ändern“.

## Wo liegt was?

| Datei | Inhalt | Im Repo? |
|---|---|---|
| `.env` | Kennung und Passwort | nein |
| `.cookies.json` | Sitzung des letzten Logins | nein |
| `config.json` | ILIAS-Adresse, Zielordner, Semester | nein |
| `<Zielordner>/.ilias-sync.json` | bestätigte und abgewählte Kurse, geladene Dateien | nein |

Die Zugangsdaten bleiben auf deinem Rechner. Das Passwort wird nur an das Login-Formular deiner Hochschule übergeben und nirgends sonst gespeichert.

## Ohne Claude benutzen

Die Skripte laufen auch direkt:

```bash
cd ~/.claude/skills/ilias-sync/scripts
./login.py                                   # anmelden
./ilias.py courses                           # Kurse nach Semester
./ilias.py setup ~/Uni/WiSe26 --category "Wintersemester 2026"
./ilias.py select ~/Uni/WiSe26 1234567="Mathe" 1234568="Statistik"
./ilias.py plan ~/Uni/WiSe26 && ./ilias.py download ~/Uni/WiSe26
```

Alle Befehle: `./ilias.py` ohne Argumente.
