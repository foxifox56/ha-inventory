# iPhone, Ingress und PWA-Entscheidung

## Vergleich

| Möglichkeit | Anmeldung und Netzwerk | iPhone-Start | Bewertung |
| --- | --- | --- | --- |
| iOS-Kurzbefehle / Companion-Deep-Link | Bleibt im Home-Assistant-Konto und verwendet dessen Anmeldung. Öffnet keinen zusätzlichen Port. | Der Companion URL Handler kann zu einer Home-Assistant-Frontend-Route navigieren. Eine Ingress-App-Route wird dadurch nicht als stabiler Direktstart garantiert. In deinem bisherigen Versuch landete der Kurzbefehl auf der HA-Startseite. | Sicher als optionaler Shortcut, aber erfüllt den direkten Lager-App-Start derzeit nicht zuverlässig. |
| PWA innerhalb Home Assistant Ingress | Ingress behält die Home-Assistant-Anmeldung und erfordert keinen zusätzlichen Port. | Manifest, Startpfad und Service-Worker-Scope müssten zum dynamischen Ingress-Pfad passen. iOS Home-Screen-Apps haben einen eigenen Speicherbereich; seit iOS 17.2 können Cookies beim Erstellen übernommen werden, aber spätere Sitzungs- und Ingress-Änderungen müssen auf echten Geräten getestet werden. | Der sicherste Kandidat, weil Ingress die bestehende Zugangsschranke bleibt. Technisch noch nicht freigegeben. |
| Eigenständige PWA mit eigener HTTPS-Adresse | Benötigt einen separaten, sicheren HTTPS-Zugang und einen geprüften Authentifizierungsweg zu Home Assistant. Ein eigener Port ohne Authentifizierung wäre unsicher. | Bietet den direktesten App-Start, aber Weiterleitung, Anmeldung, Sitzungserneuerung und Logout müssten als eigener Produktpfad funktionieren. | Für 0.2 nicht implementiert. Keine Ports, Proxy-Regeln oder zusätzliche Cloud-Datenbank werden eingerichtet. |

## Empfehlung

Vorerst HA Inventory über Ingress öffnen. Der Companion-Deep-Link bleibt eine mögliche Verknüpfung, falls er in der konkreten Installation reproduzierbar auf die App führt. Eine Ingress-PWA ist die sicherste nächste Option, aber erst nach einem echten iPhone-Test mit lokaler HA-URL und Nabu Casa. Eine unabhängige PWA ist erst vertretbar, wenn es einen separat abgesicherten HTTPS-Zugang gibt, der Home-Assistant-Authentifizierung und Rechte nachvollziehbar erhält.

HA Inventory öffnet keinen Host-Port und fügt keine zweite Cloud-Datenbank ein. Nabu Casa beziehungsweise ein anderer externer HA-Zugang darf nicht als Begründung verwendet werden, die App direkt und ungeschützt auf einen Port zu legen.

## Barcode-Scanner

Version 0.3 vendort `@zxing/browser` 0.2.1 lokal in der App, anstatt ein CDN zur Laufzeit aufzurufen. Beim Antippen des Scanners fordert der Browser Zugriff auf die nach hinten gerichtete Kamera an. Die Browser-API benötigt einen sicheren Kontext (normalerweise HTTPS) und eine erteilte Kameraberechtigung. ZXing dokumentiert, dass iOS vor 14.3 Kamera-WebRTC nur in Safari bereitstellt; neuere iOS-Versionen unterstützen WebRTC auch in Drittanbieter-Browsern. Das ist keine Garantie, dass jeder Ingress-/Nabu-Casa-/iOS-Kontext funktioniert. Die manuelle Eingabe sowie Tastatur-Scanner bleiben verfügbar.

Ein bekannter Barcode öffnet die Details. Bei unbekannten Codes versucht das Backend über ausgehendes HTTPS die Produktdatenquelle Open Facts und füllt danach das editierbare Artikelformular vor. Wenn die Quelle offline ist oder keinen Treffer hat, bleibt das normale Formular mit Barcode verfügbar. Scans führen weder eine Artikelerstellung noch eine Bestandsänderung aus.

## In 0.2 umgesetzt

- Mobile-first Web-Oberfläche mit Start-, Suche-, Scanner- und Lagerorte-Navigation, Kartenansicht, Touch-Zielen, Desktop-Layout und System-Dark-Mode.
- ZXing-Kamera-Decoder im Scanner-Dialog, sofern Browser, HTTPS-Kontext und Berechtigungen ihn erlauben; manuelle Eingabe ist immer verfügbar.
- App bleibt hinter Home Assistant Ingress. Der Barcode-Scanner nutzt keine externe Laufzeit-CDN.
- Backend-Produktsuche über den lokalen, ingress-geschützten API-Endpunkt; an Open Facts wird nur der Barcode gesendet. Bilder werden über den vertrauenswürdigen Facts-Bildhost geladen und nicht offline gecacht.

## Noch offen

- Kein Web-App-Manifest, kein Service Worker, keine Offline-Caches und keine iOS-Standalone-Metadaten. Ein Homescreen-Symbol startet daher noch keine eigenständige HA-Inventory-PWA.
- Die HA-Companion-Verknüpfung auf den Ingress-Pfad wurde nicht als verlässlicher Direktstart bestätigt; dein bisheriger Kurzbefehl führte zurück auf die HA-Startseite.
- Eine PWA innerhalb Ingress muss mit dem konkreten dynamischen Ingress-Pfad, Nabu Casa, Cookie-/Sitzungserneuerung, Logout und Service-Worker-Scope auf dem iPhone verifiziert werden.
- Der ZXing-Code hat automatisierte Schnittstellentests; die Kamera wurde nicht auf einem echten iPhone getestet. Ein Kamera-Permission-/Decode-Test auf iOS bleibt offen.
- Eine eigenständige HTTPS-PWA mit eigener Authentifizierung sowie externe API-Credentials werden nicht angeboten.

## Quellen

- [Home Assistant Companion URL Handler](https://companion.home-assistant.io/docs/integrations/url-handler/)
- [Home Assistant Ingress: Authentifizierung und dynamischer Pfad](https://developers.home-assistant.io/docs/apps/ingress/)
- [ZXing Browser API](https://github.com/zxing-js/browser)
- [ZXing iOS/WebRTC-Hinweise](https://github.com/zxing-js/library#readme)
- [Apple: Web-Apps auf dem Home Screen](https://developer.apple.com/videos/play/wwdc2023/10120/)
- [WebKit: Cookies beim Hinzufügen zum Home Screen in iOS 17.2](https://webkit.org/blog/14787/webkit-features-in-safari-17-2/)
