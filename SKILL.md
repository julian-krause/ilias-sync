---
name: ilias-sync
description: Lädt Kursmaterial eines Semesters von ILIAS herunter und sortiert es in einen frei gewählten Zielordner ein (z. B. in iCloud). Der erste Lauf ist eine Ersteinrichtung (Zugangsdaten, Semester, Zielordner, Kurse), danach synchronisiert jeder Lauf die bestätigten Kurse. Nutzen, wenn der User ILIAS-Dateien herunterladen, synchronisieren oder aktualisieren, den Sync einrichten oder Kurse, Semester bzw. Zielordner ändern will.
---

# ILIAS-Sync

```bash
S=~/.claude/skills/ilias-sync    # Ordner dieser Skill (steht als „Base directory“ über diesem Text)
I=$S/scripts/ilias.py            # ausführbar, uv-Shebang installiert die Abhängigkeiten
L=$S/scripts/login.py            # Login über agent-browser
```

Wo der Zustand liegt:
- `$S/config.json`: Einstellungen dieses Rechners, nämlich ILIAS-Adresse, Zielordner `SEMDIR` und die ILIAS-Kategorie des Semesters (z. B. „Wintersemester 2026“).
- `SEMDIR/.ilias-sync.json`: das **Manifest** mit den bestätigten Kursen (Kurs-Ref → Ordner), den abgewählten Kursen, umbenannten Ordnern und bereits geladenen Datei-Refs. Stimmt es, landen auch Wiederholungsläufe in denselben vereinfachten Ordnern.
- `$S/.env`: Zugangsdaten des Users. Du liest, zeigst oder änderst diese Datei nie und übergibst das Passwort nie selbst an einen Befehl.

## 0. Einstellungen laden oder Ersteinrichtung

`$I config` zeigt ILIAS-Adresse, `SEMDIR`, Kategorie und die Kurse. Damit arbeitest du in allen weiteren Schritten. Nennt der Auftrag ausdrücklich ein anderes Semester oder einen anderen Ordner, gelten für diesen Lauf die Angaben aus dem Auftrag.

Meldet der Befehl `SETUP NEEDED` oder `NO COURSES`, oder will der User den Sync einrichten, machst du die **Ersteinrichtung**. Du stellst die Fragen einzeln, kurz und ohne Erklärtext:

1. **Hochschule.** Standard ist die FH Münster. Nutzt der User ein anderes ILIAS, fragst du nach der Adresse und speicherst sie mit `$I setup --url https://…/`.
2. **Zugangsdaten.** `$L --check`. Fehlen sie: `cp -n $S/.env.example $S/.env && chmod 600 $S/.env && open -e $S/.env`, dazu ein Satz: „Trag Kennung und Passwort ein, speichere, schreib ‚ok‘.“ Will der User keine Zugangsdaten hinterlegen, überspringst du das. Dann meldet er sich bei jedem Lauf selbst an (Schritt 2, `--manual`).
3. **Anmelden** wie in Schritt 2.
4. **Semester.** `$I courses` zeigt alle ILIAS-Kategorien mit ihren Kursen. Du fragst, welches Semester synchronisiert werden soll, und schlägst die neueste Kategorie vor.
5. **Zielordner.** Der User bestimmt ihn frei. Du schlägst einen vor, der zu seinen vorhandenen Ordnern passt (z. B. neben den Ordnern früherer Semester, sonst `~/Documents/<Hochschule>/<Semester>`), und nimmst jeden anderen Pfad, den er nennt. Liegen dort schon Dateien, bleiben sie unangetastet.
6. **Kurse.** Du zeigst die Kurse des Semesters als Tabelle mit Ref, ILIAS-Titel und vorgeschlagenem **kurzem Ordnernamen** (Regeln in Schritt 3). Der User bestätigt, benennt um oder wählt Kurse ab.
7. **Speichern:**
   ```bash
   $I setup "$SEMDIR" --category "Wintersemester 2026"
   $I select "$SEMDIR" 1546399="BWL III" 1546383="Data Science" --ignore 1546405
   ```
   Abgewählte Kurse (`--ignore`) werden nie geladen und bei späteren Läufen nicht wieder nachgefragt.

Danach läuft der erste Sync sofort weiter ab Schritt 1. Jeder spätere Lauf synchronisiert genau die bestätigten Kurse, ohne nachzufragen.

### Später ändern

- **Kurse hinzufügen oder abwählen:** `$L`, dann `$I courses --current` (zeigt je Kurs `[sync -> Ordner]`, `[ignoriert]` oder `[NEU]`). Änderungen speicherst du mit `$I select "$SEMDIR" REF="Ordner" … --ignore REF …`. Ein abgewählter Kurs behält seine Dateien auf der Platte; gelöscht wird nur auf ausdrücklichen Wunsch.
- **Ordner umbenennen:** nur mit `$I mv` (Schritt 6).
- **Zielordner verlegen:** Der User verschiebt den Ordner selbst oder du tust es mit seiner Zustimmung (das Manifest liegt im Ordner und zieht mit). Danach `$I setup "<neuer Pfad>"`.
- **Neues Semester:** Ersteinrichtung ab Punkt 4 mit neuem Zielordner und neuer Kategorie. Der alte Ordner samt Manifest bleibt, wie er ist.
- **Zugangsdaten ändern:** `open -e $S/.env`.

## 1. Bestand im Zielordner prüfen

`$I inventory "$SEMDIR"`. Dann weißt du, welche Ordner und Dateien es schon gibt und welche Kurse das Manifest kennt. Eigene Ordner des Users (z. B. Projekte, Lernzettel) fasst du nie an. Der Download legt nur neue Dateien an und überschreibt nichts.
**Fertig, wenn** du dem User in 1–2 Sätzen sagen kannst, was schon da ist.

## 2. Login + Cookies

Die ILIAS-Sitzung läuft schnell ab. Gespeicherte Cookies aus einem früheren Lauf taugen deshalb nicht: Bei **jedem Lauf** meldest du dich neu an, direkt vor `courses`. Das macht `$L` über Vercel **agent-browser** (eigener Chrome ohne Fenster, Sitzung `ilias`). Der Browser des Users wird nicht benutzt.

```bash
$L          # meldet an, schreibt .cookies.json, schließt den Browser
```

Die Zugangsdaten liest das Skript aus `$S/.env` (`ILIAS_USER`, `ILIAS_PASSWORD`) oder aus gleichnamigen Umgebungsvariablen.

Je nach erster Zeile der Ausgabe, ohne Umwege und ohne Erklärungen an den User:
- `LOGIN OK`: weiter mit Schritt 3.
- `NO CREDENTIALS`: sofort `$L --manual` starten. Das öffnet ein sichtbares Browserfenster und wartet bis zu 5 Minuten. Dem User schreibst du nur: „Bitte im geöffneten Fenster anmelden.“ In der Zusammenfassung nennst du in einem Satz die `.env`, damit der nächste Lauf ohne ihn auskommt.
- `LOGIN FAILED`: Kennung oder Passwort wurden abgelehnt. Nicht erneut versuchen (Kontosperre). Du sagst es dem User in einem Satz und startest `$L --manual`.
- `LOGIN STUCK`: unbekannte Zwischenseite, etwa ein zweiter Faktor oder eine Startseite ohne Anmeldeformular. Der Browser bleibt offen. Du siehst mit `agent-browser --session ilias snapshot -i` nach, was verlangt wird. Braucht es den User, startest du `$L --manual`.
- `MISSING`: `npm install -g agent-browser && agent-browser install`, dann erneut `$L`.

Meldet `ilias.py` später `SESSION EXPIRED`, führst du `$L` noch einmal aus und startest den Befehl erneut. Meldet `ilias.py` oder `$L` `NETWORK`, antwortet ILIAS nicht (Störung bei der Hochschule oder keine Verbindung; jede Anfrage hat ein Zeitlimit). Ein neuer Login hilft dann nicht: Du brichst den Lauf ab, sagst dem User in einem Satz, dass ILIAS gerade nicht erreichbar ist und er den Sync später erneut starten soll. Hat ein anderer Skill den Lauf angestoßen, meldest du ihm keinen erfolgreichen Sync (kein `sync-done`).

## 3. Kurse abgleichen

`$I courses --current` zeigt die Kurse in allen ILIAS-Kategorien, deren Name die eingestellte Kategorie enthält, und markiert jeden Kurs. Ein Semester kann über mehrere Kategorien verteilt sein, z. B. „Wintersemester 2026“ und „Wintersemester 2026/2027“. Steht ein Kurs auch in einer älteren Kategorie (Wiederholer), nimmst du nur die Instanz aus dem aktuellen Semester.

- **`NEW 0`:** Die Kursliste gilt als bestätigt. Du gehst ohne Rückfrage zu Schritt 4. Das ist der Normalfall, auch bei Routine-Läufen, die ein anderer Skill anstößt (z. B. ein wöchentlicher Sync aus `kurs-tutor`).
- **`NEW n`:** Der User ist einem Kurs neu beigetreten. Nur diese Kurse zeigst du ihm als Tabelle mit Ref, ILIAS-Titel und vorgeschlagenem kurzem Ordnernamen und fragst: synchronisieren oder abwählen? Die Antwort speicherst du mit `$I select` (Schritt 0).
- **`GONE`:** Ein bestätigter Kurs steht nicht mehr unter den Mitgliedschaften. Du erwähnst es in der Zusammenfassung; die Dateien bleiben.

Ordnernamen: Kennt das Manifest einen Kurs schon, bleibt dessen Name. Sonst richtest du dich nach den vorhandenen Ordnern des Users, zum Beispiel `Webentwicklung II` ohne Bindestrich, `Marketing` statt „Grundlagen des Marketing BWI“. Erfundene Abkürzungen wie „BPL“ vermeidest du, der User soll den Namen ohne Nachfragen verstehen. Ein Ordner darf ein Unterordner sein (`BWL III/Marketing`), und zwei Kurse dürfen in denselben Ordner laufen.

Bestätigen lässt du nur, was wirklich neu ist: neue Kurse samt Ordnernamen, Beitritte (Schritt 4) und Löschungen von Duplikaten (Schritt 7).

## 4. Plan erstellen

`$I plan "$SEMDIR"` geht alle bestätigten Kurse rekursiv durch (Ordner und Gruppen) und speichert das Ergebnis in `.ilias-plan.json`. Einzelne Kurse planst du mit `$I plan "$SEMDIR" 1546399="BWL III" …`. Ausgegeben wird `+` für neue Dateien und `~` für alles, was keine Datei ist. Die `~`-Einträge prüfst du so:
- **Weblink auf einen anderen ILIAS-Kurs** (Ziel `…/go/crs/…`, oft mit Zugangscode `rcode…`): Beitreten ändert die Mitgliedschaften des Users, deshalb vorher fragen. Mit Zustimmung trittst du im Browser bei: `$L --keep` lässt die angemeldete Sitzung offen, dann `agent-browser --session ilias open <Link>`, `snapshot -i`, `click @eN`, am Ende `agent-browser --session ilias close`. Liegt das Material in Untergruppen, gehört dazu auch die passende Gruppe (Dozent bzw. Termin mit dem Hauptkurs abgleichen). Den Kurs nimmst du dann mit `$I select` auf, mit demselben Ordnernamen.
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
- Eine Gruppe, die nur den Kurs spiegelt (z. B. „Englisch I Gr. 2“), wird in den Kursordner aufgelöst: `$I mv "$SEMDIR" "Englisch I/Englisch I Gr. 2" "Englisch I"`.
- Ein Ordner, der nur eine Datei enthält, wird in den übergeordneten Ordner aufgelöst.

Hast du Ordner nach dem Anlegen der `Links.md` verschoben, passt du die Pfadangaben darin an.

## 7. Abschluss

Lass `$I dupes "$SEMDIR"` laufen. Für doppelte Dateien zeigst du dem User die Gruppen. Gelöscht wird nur, wenn er es bestätigt. Danach fasst du zusammen:
- eine Tabelle pro Kurs mit Anzahl der neuen Dateien und Inhalt
- leere Kurse
- übersprungene Elemente (Tests, Abgaben mit Frist)
- Beitritte, die du erledigt hast
- nach einer Ersteinrichtung: Zielordner, Semester und die bestätigten Kurse in zwei Zeilen
