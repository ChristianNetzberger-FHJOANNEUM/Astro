# Astro-VR Dauerbetrieb (Windows)

> Quelle: Chat mit Cursor, 2026-10-11 · Thema: Quest 3 über `https://vr.netzberger.at:8443/vr-view`, Bestandsaufnahme vor dem Dauerbetrieb
> Stand: **Skripte liegen unter `deployment/windows/`, Aufgaben sind nicht registriert.** Laufende Prozesse, Zertifikat, Firewall und DNS wurden dafür nicht verändert. Aktivierung erst mit `-Confirm` nach eigener Freigabe.

Die immersive Quest-Seite ist im Hausnetz eingerichtet. Diese Seite hält fest, was dafür läuft, was einen Neustart nicht übersteht, und was der externe Auftrag richtig und falsch einschätzt. Sie ersetzt nicht die [Autostart-Spec](mele-autostart-dev-prod-spec.md) und nicht die [Feldnetz-Spec](mele-feldnetz-quest-spec.md).

## Was die Quest braucht

Nach einem Neustart muss diese Adresse ohne PowerShell-Fenster funktionieren:

`https://vr.netzberger.at:8443/vr-view`

Dafür müssen drei Prozesse laufen, in dieser Reihenfolge:

1. Technitium DNS, damit `vr.netzberger.at` auf den MeLE zeigt.
2. MeLE-App auf Port 8082, damit Caddy ein Ziel hat.
3. Caddy auf Port 8443, damit die Quest HTTPS und einen sicheren Kontext bekommt.

NINA, SynScan und PHD2 braucht diese URL nicht. Port 8082 bleibt HTTP für iPad und Entwicklung. Caddy gibt nur die VR-Pfade frei.

## Netz, Stand 2026-10-11

| Rolle | Adresse |
|---|---|
| MeLE (ASTRO) | `192.168.0.176` |
| Meta Quest 3 | `192.168.0.108` |
| ZTE-Router | `192.168.0.1` |
| Haus-LAN | `192.168.0.0/24` |

Zwei Auflösungen, beide unverändert lassen:

| Resolver | Ergebnis |
|---|---|
| Technitium auf `192.168.0.176` | `A 192.168.0.176` |
| System-DNS des MeLE, öffentlich | `CNAME w01cda5d.kasserver.com`, danach `85.13.154.237` |

Die Quest benutzt die lokale Antwort. Der Windows-Resolver des MeLE nicht. Eine Prüfung der URL ohne festes Ziel `192.168.0.176` läuft deshalb gegen den Webspace und läuft in Port 8443 ins Leere. Das ist kein Fehler von Caddy. Die öffentliche CNAME-Kette wird nicht gelöscht und nicht umgebogen. Keine Portweiterleitung am Router.

## Ist-Stand der Prozesse

Nur gelesen. Kein Dienst neu gestartet, keine Regel geändert.

| Komponente | Prozess | Sitzung | Startart heute | Übersteht Abmeldung? |
|---|---|---|---|---|
| Technitium DNS | `DnsService.exe`, PID auf Port 53 und 5380 | 0 (Dienst) | Windows-Dienst `DnsService`, Startmodus **Auto**, Konto `NT SERVICE\DnsService` | ja |
| Caddy | `C:\Caddy\caddy.exe run --config C:\Caddy\Caddyfile` | 1 (angemeldet) | manuell, kein Dienst, keine Aufgabe | nein |
| MeLE-App | `C:\Python\310\python.exe -m app_mele` | 1 (angemeldet) | manuell, kein Dienst, keine Aufgabe | nein |
| weather_server | eigene Aufgabe | Anmeldung | Task `Astro-weather_server` | nur nach Anmeldung |
| Zertifikatserneuerung | — | — | keine geplante Aufgabe | nein |

Technitium ist damit der einzige der drei VR-Bausteine, der das Ziel „Automatischer Start mit Windows“ schon erfüllt. Eine zweite Instanz darf nicht installiert werden.

Pfad des Dienstes: `C:\Program Files (x86)\Technitium\DNS Server\DnsService.exe`, Daten unter `C:\ProgramData\Technitium DNS Server`. Verwaltung weiter auf Port 5380.

Caddy und die App liefen am 2026-10-10 ab etwa 23:33 bzw. 23:47 in Sitzung 1. Ein Windows-Dienst wäre Sitzung 0. Beide Prozesse sind also an die Anmeldung von Chris gebunden, auch wenn gerade kein PowerShell-Fenster sichtbar ist.

Die App nutzt den System-Python `C:\Python\310\python.exe`, nicht `.venv`. Arbeitsverzeichnis muss das Repo `c:\Astro\Git\Astro` sein, weil `app_mele` nur von dort als Modul startet. `ui.run` hat `show=True` und `reload=False`. Ein Dienst würde versuchen, ein Browserfenster in Sitzung 0 zu öffnen. `--no-show` ist in der Autostart-Spec vorgesehen und im Code noch nicht vorhanden.

## Caddy

Dateien, unverändert lassen, bis Phase 2 freigegeben ist:

- Programm: `C:\Caddy\caddy.exe`
- Konfiguration: `C:\Caddy\Caddyfile`

Verhalten der laufenden Datei:

- `auto_https disable_redirects`
- Site `https://vr.netzberger.at:8443`
- TLS-Dateien aus dem Posh-ACME-Ordner von Chris: `fullchain.cer` und `cert.key`
- Reverse-Proxy nur für `/vr-view`, `/vr/current`, `/vr/current/*`, `/mele-static/*`, `/mele-media/*`, `/mele-export/*` nach `127.0.0.1:8082`
- alles andere antwortet `Nicht freigegeben` mit 404

Der Admin-Endpunkt von Caddy hört auf `127.0.0.1:2019` (derselbe Prozess). Ein Neuladen des Zertifikats geht darüber, ohne den MeLE neu zu starten. Port 2019 darf nicht in die Firewall nach außen.

## Zertifikat

Ausstellerweg: Posh-ACME, Let's Encrypt Produktion, Plugin DeSEC, delegierte Zone `acme.netzberger.at`. Das Zertifikat wurde nicht neu ausgestellt.

| Feld | Wert |
|---|---|
| Name | `CN=vr.netzberger.at` |
| Gültig von | 2026-10-10 20:10 |
| Gültig bis | 2027-01-08 19:10 (`CertExpires` 2027-01-08T18:10:42Z) |
| Erneuern ab | 2026-12-09T18:10:42Z (`RenewAfter`) |
| Auftragsstatus | `valid` |
| Ordner | `C:\Users\Chris\AppData\Local\Posh-ACME\LE_PROD\3849034426\vr.netzberger.at\` |

`expires` im Auftragsobjekt (2026-10-17) ist das ACME-Auftragsfenster, nicht das Zertifikatsende.

NTFS auf `fullchain.cer` und `cert.key`, geerbt: `SYSTEM` Vollzugriff, Administratoren Vollzugriff, `ASTRO\Chris` Vollzugriff. Ein Dienst unter `LocalSystem` kann die Dateien heute lesen, auch ohne dass das Profil geladen ist. Trotzdem bleibt der Pfad an das Benutzerprofil gebunden. Zugangsdaten für deSEC liegen in `pluginargs.json` in demselben Ordner. Diese Datei kommt weder ins Git noch in ein Skript.

Es gibt keine geplante Aufgabe, die `Submit-Renewal` ausführt. Ohne sie läuft das Zertifikat am 2027-01-08 ab, auch wenn Caddy als Dienst läuft.

## Firewall (behalten)

Alle drei Regeln: aktiv, eingehend, Profil Privat, Aktion Zulassen.

| Regel | Protokoll | Port | Remote |
|---|---|---|---|
| Technitium DNS TCP 53 | TCP | 53 | nur `192.168.0.108` (Quest) |
| Technitium DNS UDP 53 | UDP | 53 | nur `192.168.0.108` (Quest) |
| Technitium DNS Notebook Test | UDP | 53 | nur `192.168.0.101` |
| Caddy VR HTTPS 8443 | TCP | 8443 | `192.168.0.0/24` |

DNS ist nicht für das ganze LAN offen. Die Notebook-Regel nicht löschen, nur weil die Quest sie nicht braucht. Keine weiteren Ports, keine Weiterleitung am ZTE.

## Prüfung des externen Auftrags

Der Auftrag trennt Bestandsaufnahme und administrative Änderung. Das passt. Phase 1 ist hiermit erledigt. Phase 2 wird nicht ausgeführt, bevor sie freigegeben ist.

Was übernommen wird:

- Technitium nicht noch einmal installieren. Der Dienst `DnsService` ist schon automatisch.
- DNS-Zone, Quest und Router nicht anfassen.
- Dieselbe Caddyfile behalten. Keine zweite Caddy-Instanz, solange Port 8443 belegt ist.
- Dieselbe MeLE-App. Keine zweite Instanz auf Port 8082.
- Zertifikat nicht neu ausstellen. Erneuerung über die vorhandene Posh-ACME-Bestellung, danach Caddy neu laden, nicht den PC neu starten.
- Geheimnisse und private Schlüssel nicht ins Git.
- Vorhandene Firewall-Regeln behalten, nicht verbreitern.
- Skripte später idempotent, mit Rückfrage vor `sc`, Aufgabenplanung und NTFS-Änderungen.

Was nicht übernommen wird:

- Die MeLE-App wird nicht als WinSW-Dienst eingerichtet. `show=True` öffnet ein Browserfenster. NINA, SynScan und PHD2 brauchen eine interaktive Sitzung. Die beschlossene Form bleibt die Aufgabe `Astro-mele_app` bei der Anmeldung von Chris, siehe Autostart-Spec. Ein Start vor der Anmeldung ist nur der Webserver, und erst nachdem `--no-show` existiert.
- Caddy braucht keinen zusätzlichen WinSW-Binary, solange eine Aufgabe „Beim Systemstart, ob der Benutzer angemeldet ist oder nicht“ denselben Prozess startet. WinSW bleibt eine mögliche Alternative, nicht die Vorgabe.
- Die Zertifikate müssen nicht sofort nach `C:\ProgramData\AstroVR\` umgezogen werden. `SYSTEM` darf sie im Profil lesen. Ein Umzug ändert die Caddyfile und den Erneuerungspfad und ist ein eigener, freizugebender Schritt. Bis dahin bleibt der Profilpfad die laufende Ablage.

## Phase 2, Skripte fertig, nicht aktiviert

Freigabe des externen Auftrags vom 2026-10-11, mit den drei Ergänzungen Startverzögerung, tägliche Erneuerungsprüfung und Erreichbarkeitstest. Umgesetzt nur als Dateien. `Register-AstroVrTasks.ps1` ohne `-Confirm` registriert nichts. Mit `-Confirm` registriert es und startet nicht. Kein Skript beendet einen laufenden Prozess.

| Aufgabe | Konto | Trigger | Befehl |
|---|---|---|---|
| `AstroVR-Caddy` | `SYSTEM` | Systemstart, Verzögerung 45 s, Neustart 5× / 1 min | `Start-AstroVrCaddy.ps1`, vorher `caddy validate`. Port 8443 belegt → Exit 0 |
| `Astro-mele_app` | `ASTRO\Chris`, interaktiv | Anmeldung, Verzögerung 30 s, kein `RestartCount` | `C:\Python\310\python.exe -m app_mele` in `C:\Astro\Git\Astro`. Port 8082 belegt → Exit 0 |
| `AstroVR-CertRenewal` | `ASTRO\Chris`, interaktiv | täglich 09:15, versäumte Läufe nachholen | Posh-ACME-Auftrag wiederverwenden. `Submit-Renewal` erst ab `RenewAfter`. Danach `caddy reload` nur wenn `fullchain.cer` sich geändert hat |

Die App bekommt absichtlich keinen Nacht-Watchdog. Die drei Minuten Wartezeit gelten nur beim Start, bis Python und das Repo da sind. Ein Absturz während der Beobachtung bleibt stehen. NINA, SynScan und PHD2 startet diese Aufgabe nicht.

Die Quest-URL ist in dieser Stufe erst nach der Anmeldung von Chris erreichbar. Caddy kann vorher laufen, die App nicht. Ein kopfloser Webserver beim Systemstart und eine getrennte interaktive Oberfläche sind die spätere Stufe. `--no-show` gibt es dafür noch nicht.

Bedienung, Rollback und Tests: [deployment/windows/README.md](../../deployment/windows/README.md). Status jederzeit mit `Get-AstroVrStatus.ps1`. Der liest DNS, Ports 53/8082/8443, HTTP 200, Zertifikatsdatum und den Vergleich von Datei und live ausgeliefertem Zertifikat.

## Sicherheitsgrenzen

- Port 53 bleibt auf Quest und die eine Notebook-Adresse beschränkt.
- Port 8443 bleibt im Hausnetz `192.168.0.0/24`.
- Port 8082 bleibt erreichbar, wie bisher. Caddy versteckt die Steuer-APIs nicht.
- Port 2019 bleibt nur auf localhost.
- `pluginargs.json` und `cert.key` werden nicht kopiert, nicht angezeigt und nicht versioniert.
- Kein automatischer Windows-Neustart durch ein Skript.

## Verwandte Seiten

- [MeLE Autostart und Entwicklungsbetrieb](mele-autostart-dev-prod-spec.md) — App-Task, `--no-show`, DEV/PROD
- [MeLE-PC Autostart](mele-pc-autostart.md) — weather_server ist der einzige Astro-Task
- [MeLE Feldnetz, Reiserouter und Quest 3](mele-feldnetz-quest-spec.md) — ADR-VR-002
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
- [astro.netzberger.at](astro-netzberger-roadmap.md) — öffentliche Website, anderer Name
