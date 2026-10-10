# Astro-VR auf Windows

Skripte für den Dauerbetrieb der Quest-Adresse `https://vr.netzberger.at:8443/vr-view`.

Stand: die Skripte liegen im Repo. **Keine Aufgabe ist registriert, kein Prozess wurde dafür gestartet oder beendet.** Aktivierung erst nach einer eigenen Freigabe, mit `-Confirm` in einer erhöhten PowerShell. Ein Neustarttest ist ein zweiter Schritt danach.

Die Quest-URL funktioniert in dieser Stufe erst nach der Anmeldung von Chris, nicht schon am Windows-Anmeldebildschirm. Technitium und, nach Aktivierung, Caddy starten vorher. Die MeLE-App öffnet ein Browserfenster und kann NINA, SynScan und PHD2 starten. Deshalb bleibt sie an der angemeldeten Sitzung.

## 1. Installation

Nur auf dem MeLE, aus einer **erhöhten** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Astro\Git\Astro\deployment\windows\Register-AstroVrTasks.ps1
```

Das zeigt den Plan und ändert nichts. Registrieren, ohne die Aufgaben zu starten:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Astro\Git\Astro\deployment\windows\Register-AstroVrTasks.ps1 -Confirm
```

Erneutes Ausführen ersetzt nur die Aufgabendefinition. Ein bereits laufender Caddy oder `python -m app_mele` wird nicht beendet. Ist Port 8443 oder 8082 belegt, beendet sich der zugehörige Starter mit Code 0 und startet keine zweite Instanz.

Technitium (`DnsService`, Startmodus Auto) wird nicht installiert und nicht verändert.

## 2. Administratorrechte

| Schritt | Rechte |
|---|---|
| Plan anzeigen, Status, `-CheckOnly` | normaler Benutzer Chris |
| `-Confirm` beim Registrieren oder Entfernen | erhöhte PowerShell, weil die Caddy-Aufgabe als `SYSTEM` beim Systemstart liegt |
| Laufender Caddy heute | Sitzung von Chris, nicht der Dienst |

`SYSTEM` darf die Zertifikatsdateien im Profil von Chris lesen. Die deSEC-Zugangsdaten bleiben in `pluginargs.json` und werden von Posh-ACME selbst geladen. Kein Skript übergibt sie.

## 3. Startreihenfolge

Nach einem späteren Neustart, sobald die Aufgaben aktiv sind:

1. Technitium, Windows-Dienst, sofort. Unverändert.
2. `AstroVR-Caddy`, 45 Sekunden nach Systemstart, Konto `SYSTEM`. Unabhängig von der Anmeldung. Bei Fehler wiederholt die Aufgabe den Start fünfmal im Abstand von einer Minute. Der Starter selbst versucht `caddy validate` bis zu fünfmal alle 20 Sekunden.
3. Anmeldung von `ASTRO\Chris`.
4. `Astro-mele_app`, 30 Sekunden nach der Anmeldung. Der Starter wartet höchstens drei Minuten auf `C:\Python\310\python.exe` und das Repo. Danach ein Prozess. Kein Neustart, wenn die App später abstürzt.
5. `AstroVR-CertRenewal`, täglich 09:15, nur wenn Chris angemeldet ist. Versäumte Läufe holt die Aufgabe nach, sobald die Sitzung da ist.

## 4. Aufgaben

| Aufgabe | Konto | Trigger | Startbefehl |
|---|---|---|---|
| `AstroVR-Caddy` | `SYSTEM`, höchste Rechte | Beim Start, Verzögerung 45 s, Neustart 5× / 1 min | `Start-AstroVrCaddy.ps1` → `C:\Caddy\caddy.exe validate`, danach `run --config C:\Caddy\Caddyfile` |
| `Astro-mele_app` | `ASTRO\Chris`, interaktiv, eingeschränkt | Bei Anmeldung, Verzögerung 30 s, kein `RestartCount` | `C:\Python\310\python.exe -m app_mele`, Arbeitsverzeichnis `C:\Astro\Git\Astro` |
| `AstroVR-CertRenewal` | `ASTRO\Chris`, interaktiv | Täglich 09:15, nachholen wenn verpasst | `Invoke-AstroVrCertRenewal.ps1` |

Die App-Aufgabe heißt `Astro-mele_app`, wie in der Autostart-Spec vorgesehen. Sie ist der erste konkrete Starter dafür. `--no-show` gibt es im Code noch nicht. NINA, SynScan und PHD2 startet sie nicht.

## 5. Test

Lesen, jederzeit, auch bevor Aufgaben existieren:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Astro\Git\Astro\deployment\windows\Get-AstroVrStatus.ps1
```

Erwartet im jetzigen Betrieb: DNS über Technitium `vr.netzberger.at` = `192.168.0.176`, TCP 53, 8082 und 8443 belegt, HTTPS 200 über diese Adresse, Zertifikat gültig, die drei Aufgaben als `NOTE` nicht registriert. Der Windows-Resolver des MeLE liefert die öffentliche CNAME-Kette zum Webspace. Das Skript prüft die Quest-Strecke deshalb gegen die Technitium-Adresse, nicht gegen den System-Resolver.

Nur den Erneuerungsauftrag ansehen, ohne Let's Encrypt aufzurufen:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Astro\Git\Astro\deployment\windows\Invoke-AstroVrCertRenewal.ps1 -CheckOnly
```

Nach einer späteren Aktivierung und einem freigegebenen Neustart:

1. Vor der Anmeldung: DNS und TCP 8443 da, TCP 8082 noch nicht.
2. Nach der Anmeldung von Chris: TCP 8082 da, `https://vr.netzberger.at:8443/vr-view` liefert 200, das live ausgelieferte Zertifikat hat denselben Fingerabdruck wie `fullchain.cer`.
3. Eine zweite Anmeldung oder ein zweiter Task-Lauf darf keinen zweiten Prozess auf 8082 oder 8443 erzeugen.

## 6. Fehlerdiagnose

| Symptom | Nachsehen |
|---|---|
| Quest findet den Namen nicht | Dienst `DnsService`, dann `Resolve-DnsName vr.netzberger.at -Server 192.168.0.176` |
| HTTPS fehlgeschlagen, App lokal da | `C:\ProgramData\AstroVR\logs\caddy-task.log` und `caddy-stdout.log` |
| Port 8082 fehlt nach der Anmeldung | `C:\Astro\Git\Astro\data\vr-boot\mele-app.log` |
| Zertifikat läuft ab | `data\vr-boot\cert-renew.log`. Die Aufgabe läuft nur in der Sitzung von Chris |
| Datei neu, Browser noch alt | Statuszeile `live certificate`. Reload ist dann fehlgeschlagen, die alte Datei ist nicht gelöscht |

Protokolle über 5 MB werden beim nächsten Start nach `.old` verschoben.

## 7. Rollback

Aufgaben entfernen, Prozesse laufen weiter:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Astro\Git\Astro\deployment\windows\Unregister-AstroVrTasks.ps1 -Confirm
```

Damit ist der Zustand vor der Aktivierung wiederhergestellt: Caddy und die App starten nur von Hand, Technitium bleibt Dienst. Die Caddyfile, die Zone und die Firewall bleiben die ganze Zeit unberührt.

## 8. Zertifikatserneuerung

Posh-ACME 4.x, Konto `3849034426`, Server Let's Encrypt Produktion, Auftrag `vr.netzberger.at`, Plugin DeSEC aus dem vorhandenen Profil.

Der 9. Dezember 2026 ist der Beginn des Fensters (`RenewAfter`), kein einmaliger Termin. Die tägliche Aufgabe ruft `Submit-Renewal` erst auf, wenn dieser Zeitpunkt erreicht ist. `-Force` wird nicht verwendet. Eine neue Bestellung wird nicht angelegt.

Nach einer tatsächlichen Änderung von `fullchain.cer` lädt das Skript Caddy neu (`caddy reload` über `127.0.0.1:2019`). Schlägt das fehl, bleiben die neuen Dateien liegen und der laufende Caddy behält das bereits geladene Zertifikat. Der MeLE wird dafür nicht neu gestartet.

Liegt zwischen dem 9. Dezember 2026 und dem 8. Januar 2027 keine Anmeldung von Chris, findet keine Erneuerung statt. Das gehört zu dieser Stufe.

## 9. Sicherheit

- DNS-Regeln bleiben auf `192.168.0.108` und die Notebook-Regel auf `192.168.0.101` beschränkt. TCP 8443 bleibt `192.168.0.0/24`.
- Keine Router-Weiterleitung, keine Änderung an der Quest, keine zweite DNS-Zone.
- `pluginargs.json` und `cert.key` werden nicht gelesen, nicht kopiert und nicht ins Git gelegt.
- Port 2019 bleibt nur auf localhost.
- Die Skripte starten keinen Windows-Neustart.
- `scripts\free-port-8082.ps1` beendet jeden Prozess auf 8082. Diese Starter rufen es nicht auf.

## Später, nicht in diesen Skripten

Ein kopfloser Webserver beim Systemstart und eine getrennte interaktive Oberfläche für NINA und SynScan würden die Quest-URL auch ohne Anmeldung erreichbar machen. Dafür fehlt `--no-show` noch. Das ist die nächste Ausbaustufe, nicht diese.
