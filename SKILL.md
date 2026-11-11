---
name: ilias-sync
description: Lädt Kursmaterial eines Semesters von ILIAS (ilias.fh-muenster.de) herunter und sortiert es in iCloud unter "FH Münster/<N>. Semester" ein. Nutzen, wenn der User ILIAS-Dateien herunterladen, synchronisieren oder aktualisieren will.
---

# ILIAS → iCloud Semester-Sync

Das Semester ist der Parameter: der Zielordner `SEMDIR` ist
`~/Library/Mobile Documents/com~apple~CloudDocs/FH Münster/<N>. Semester`, die ILIAS-Kategorie heißt z.B. „Wintersemester 2026“ oder „Sommersemester 2027“. Fehlt eins davon, frag nach (aus dem Ordnernamen lässt sich die ILIAS-Kategorie nicht ableiten: ungerade Semester sind nicht immer WiSe).

Alle Schritte laufen über ein Skript, das seinen Zustand im **Manifest** `SEMDIR/.ilias-sync.json` hält (Kurs-Ref → lokaler Ordner, umbenannte Ordner, bereits geladene Datei-Refs). Wenn das Manifest stimmt, landen auch Wiederholungsläufe in denselben vereinfachten Ordnern.

```bash
I=~/.claude/skills/ilias-sync/scripts/ilias.py   # ausführbar, uv-Shebang installiert die Abhängigkeiten
```

## 1. Bestand in iCloud prüfen

`$I inventory "$SEMDIR"`. Dann weißt du, welche Ordner und Dateien es schon gibt und welche Kurse das Manifest kennt. Eigene Ordner des Users (z.B. Projekte, Lernzettel) fasst du nie an. Der Download legt nur neue Dateien an und überschreibt nichts.
**Fertig, wenn** du dem User in 1–2 Sätzen sagen kannst, was schon da ist.

## 2. Login + Cookies

Die ILIAS-Sitzung läuft schnell ab. Gespeicherte Cookies aus einem früheren Lauf taugen deshalb nicht: Bei **jedem Lauf** meldest du dich neu an, direkt vor `courses`. Das macht ein Skript über Vercel **agent-browser** (eigener Chrome ohne Fenster, Sitzung `ilias`). `browser-use` und der Chrome des Users werden für ILIAS nicht mehr benutzt.

```bash
L=~/.claude/skills/ilias-sync/scripts/login.py
$L          # meldet an, schreibt .cookies.json, schließt den Browser
```

Die Zugangsdaten liest das Skript aus `~/.claude/skills/ilias-sync/.env` (`ILIAS_USER`, `ILIAS_PASSWORD`, vom User eingetragen) oder aus gleichnamigen Umgebungsvariablen. Du liest, zeigst oder änderst die `.env` nie und übergibst das Passwort nie selbst an einen Befehl.

Je nach erster Zeile der Ausgabe, ohne Umwege und ohne Erklärungen an den User:
- `LOGIN OK`: weiter mit Schritt 3.
- `NO CREDENTIALS`: sofort `$L --manual` starten. Das öffnet ein sichtbares Browserfenster und wartet bis zu 5 Minuten. Dem User schreibst du nur: „Bitte im geöffneten Fenster anmelden.“ In der Zusammenfassung nennst du in einem Satz die `.env`, damit der nächste Lauf ohne ihn auskommt.
- `LOGIN FAILED`: Die FH hat Kennung oder Passwort abgelehnt. Nicht erneut versuchen (Kontosperre). Du sagst es dem User in einem Satz und startest `$L --manual`.
- `LOGIN STUCK`: unbekannte Zwischenseite, etwa ein zweiter Faktor. Der Browser bleibt offen. Du siehst mit `agent-browser --session ilias snapshot -i` nach, was verlangt wird. Braucht es den User, startest du `$L --manual`.
- `MISSING`: `npm install -g agent-browser && agent-browser install`, dann erneut `$L`.

Meldet `ilias.py` später `SESSION EXPIRED`, führst du `$L` noch einmal aus und startest den Befehl erneut. Meldet `ilias.py` oder `$L` `NETWORK`, antwortet ILIAS nicht (Störung bei der FH oder keine Verbindung; jede Anfrage hat ein Zeitlimit). Ein neuer Login hilft dann nicht: Du brichst den Lauf ab, sagst dem User in einem Satz, dass ILIAS gerade nicht erreichbar ist und er den Sync später erneut starten soll, und führst kein `sync-done` aus.

## 3. Kurse anzeigen und bestätigen lassen

Mit `$I courses --match "Wintersemester 2026"` siehst du die Kurse in allen ILIAS-Kategorien, deren Name den Text enthält. Ein Semester kann über mehrere Kategorien verteilt sein, z.B. „Wintersemester 2026“ und „Wintersemester 2026/2027“. Steht ein Kurs auch in einer älteren Kategorie (Wiederholer), nimmst du nur die Instanz aus dem aktuellen Semester.

Zeig die Kurse als Tabelle mit Ref, ILIAS-Titel und vorgeschlagenem **kurzem Ordnernamen**. Kennt das Manifest einen Kurs schon, übernimmst du dessen Ordnernamen. Sonst richtest du dich nach den Namen der Vorsemester, zum Beispiel `Webentwicklung II` ohne Bindestrich, `Marketing` statt „Grundlagen des Marketing BWI“. Erfundene Abkürzungen wie „BPL“ vermeidest du, der User soll den Namen ohne Nachfragen verstehen.
**Fertig, wenn** der User die Kursliste und die Ordnernamen bestätigt hat. Vorher lädst du nichts herunter.

**Routine-Lauf** (z. B. der wöchentliche Sync aus `kurs-tutor`): Kennt das Manifest alle Kurse, die `courses` für das Semester liefert, gelten Kursliste und Ordnernamen als bestätigt. Du gehst dann direkt zu Schritt 4 mit allen Kursen aus dem Manifest (`Ref="Ordner"` genau wie dort eingetragen, auch wenn der Ordner ein Unterordner ist, z. B. `BWL III/Marketing`). Bestätigen lässt du nur, was wirklich neu ist: einen neuen Kurs samt Ordnernamen, Beitritte (Schritt 4) und Löschungen von Duplikaten (Schritt 7).

## 4. Plan erstellen

`$I plan "$SEMDIR" 1546399="BWL III" 1546383="Data Science" ...` geht die Kurse rekursiv durch (Ordner und Gruppen) und speichert das Ergebnis in `.ilias-plan.json`. Ausgegeben wird `+` für neue Dateien und `~` für alles, was keine Datei ist. Die `~`-Einträge prüfst du so:
- **Weblink auf einen anderen ILIAS-Kurs** (Ziel `ilias…/go/crs/…`, oft mit Zugangscode `rcode…`): Beitreten ändert die Mitgliedschaften des Users, deshalb vorher fragen. Mit Zustimmung trittst du im Browser bei: `$L --keep` lässt die angemeldete Sitzung offen, dann `agent-browser --session ilias open <Link>`, `snapshot -i`, `click @eN`, am Ende `agent-browser --session ilias close`. Liegt das Material in Untergruppen, gehört dazu auch die passende Gruppe (Dozent bzw. Termin mit dem Hauptkurs abgleichen). Den Kurs nimmst du dann als eigenen Eintrag in `plan` auf, mit demselben Ordnernamen.
- **Externe Weblinks** (GitLab, YouTube, Specs): kommen in `<Kurs>/Links.md`.
- **Tests, Foren, Übungsabgaben (exc)**: werden nicht heruntergeladen. Abgabefristen nennst du in der Zusammenfassung.

## 5. Herunterladen mit Duplikatcheck

`$I download "$SEMDIR"`. Eine Datei wird übersprungen, wenn eine dieser Bedingungen zutrifft:
- Ihr Ref steht schon im Manifest.
- Irgendwo im SEMDIR liegt eine Datei mit gleichem Namen und gleicher Größe.
- Ihr SHA-256 stimmt mit einer vorhandenen Datei überein. So werden auch Dateien erkannt, die der User umbenannt hat.

Bei gleichem Namen und anderem Inhalt bleiben beide erhalten, die neue heißt dann `(2)`. Wenn ILIAS `.py` als `…py.sec` ausliefert, korrigiert das Skript den Namen automatisch.
**Fertig, wenn** `STATS` `fail: 0` meldet. Kommt FAIL, prüfst du die Datei im Browser (`$L --keep`, dann `agent-browser --session ilias open <URL>`).

## 6. Ordnernamen vereinfachen

Ordner benennst du **ausschließlich** mit `$I mv "$SEMDIR" "<alt>" "<neu>"` um. Nur so merkt sich das Manifest die Umbenennung und künftige Läufe sortieren richtig ein. Liegt am Ziel schon ein Ordner, werden die Inhalte zusammengeführt. Leitlinien:
- Einheitliche Standardnamen: `Vorlesung`, `Übungen` (mit `Lösungen`, `Materialien`), `Tutorium`, `Material`.
- ILIAS-Schnörkel weg: „Skripte - Vorlesungen“ → `Vorlesung <Thema>`, „KI-Lernassistenz „X“ - Tool & Hinweise“ → in `Material`.
- Eine Gruppe, die nur den Kurs spiegelt (z.B. „Englisch I Gr. 2“), wird in den Kursordner aufgelöst: `$I mv "$SEMDIR" "Englisch I/Englisch I Gr. 2" "Englisch I"`.
- Ein Ordner, der nur eine Datei enthält, wird in den übergeordneten Ordner aufgelöst.

Hast du Ordner nach dem Anlegen der `Links.md` verschoben, passt du die Pfadangaben darin an.

## 7. Abschluss

Lass `$I dupes "$SEMDIR"` laufen. Für doppelte Dateien zeigst du dem User die Gruppen. Gelöscht wird nur, wenn er es bestätigt. Danach fasst du zusammen:
- eine Tabelle pro Kurs mit Anzahl der neuen Dateien und Inhalt
- leere Kurse
- übersprungene Elemente (Tests, Abgaben mit Frist)
- Beitritte, die du erledigt hast
