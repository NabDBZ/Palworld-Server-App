# -*- coding: utf-8 -*-
"""Manuel Utilisateur generique - Palworld Server Manager (corps + fusion).
Sortie: docs/Manuel_Utilisateur.pdf"""
import hashlib
import os

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, HRFlowable, Image,
                                KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "body.pdf")
COVER = os.path.join(HERE, "cover.pdf")
FINAL = os.path.join(os.path.dirname(HERE), "Manuel_Utilisateur.pdf")
IMG = os.path.join(HERE, "img")

FDIR = os.path.join(os.environ["WINDIR"], "Fonts")
pdfmetrics.registerFont(TTFont("Calibri", os.path.join(FDIR, "calibri.ttf")))
pdfmetrics.registerFont(TTFont("Calibri-Bold", os.path.join(FDIR, "calibrib.ttf")))
pdfmetrics.registerFont(TTFont("Calibri-Italic", os.path.join(FDIR, "calibrii.ttf")))
registerFontFamily("Calibri", normal="Calibri", bold="Calibri-Bold",
                   italic="Calibri-Italic", boldItalic="Calibri-Bold")

# Cascade Palette (pdf.py palette.cascade - minimal)
PAGE_BG = colors.HexColor('#f6f6f5')
TABLE_STRIPE = colors.HexColor('#ecebe8')
BORDER = colors.HexColor('#c3bfb5')
ACCENT = colors.HexColor('#207591')
TEXT_PRIMARY = colors.HexColor('#1a1917')
TEXT_MUTED = colors.HexColor('#86847c')

MARGIN = 2.0 * cm
PAGE_W, PAGE_H = A4
AVAIL_W = PAGE_W - 2 * MARGIN
H1_ORPHAN = (PAGE_H - 2 * MARGIN) * 0.20
DOC_TITLE = "Manuel Utilisateur - Palworld Server Manager"


class TocDocTemplate(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if hasattr(flowable, "bookmark_name"):
            self.notify("TOCEntry", (getattr(flowable, "bookmark_level", 0),
                                     getattr(flowable, "bookmark_text", ""),
                                     self.page,
                                     getattr(flowable, "bookmark_key", "")))


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Calibri", 7.5)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawString(MARGIN, PAGE_H - 1.1 * cm, DOC_TITLE)
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1.2)
    canvas.line(MARGIN, PAGE_H - 1.25 * cm, PAGE_W - MARGIN, PAGE_H - 1.25 * cm)
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 1.25 * cm, PAGE_W - MARGIN, 1.25 * cm)
    canvas.setFont("Calibri", 7.5)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawString(MARGIN, 0.9 * cm, "Palworld Server Manager  ·  v1.1")
    canvas.drawRightString(PAGE_W - MARGIN, 0.9 * cm, "Page %d" % doc.page)
    canvas.restoreState()


S = {
    "h1": ParagraphStyle("H1", fontName="Calibri", fontSize=20, leading=25,
                         textColor=TEXT_PRIMARY, spaceBefore=18, spaceAfter=4),
    "h2": ParagraphStyle("H2", fontName="Calibri", fontSize=14, leading=18,
                         textColor=colors.HexColor('#59523f'), spaceBefore=14,
                         spaceAfter=6),
    "h3": ParagraphStyle("H3", fontName="Calibri", fontSize=11.5, leading=15,
                         textColor=TEXT_PRIMARY, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("Body", fontName="Calibri", fontSize=10.5,
                           leading=17, textColor=TEXT_PRIMARY,
                           alignment=TA_JUSTIFY, spaceAfter=8),
    "bullet": ParagraphStyle("Bullet", fontName="Calibri", fontSize=10.5,
                             leading=16, textColor=TEXT_PRIMARY,
                             leftIndent=14, spaceAfter=3),
    "caption": ParagraphStyle("Caption", fontName="Calibri", fontSize=8.5,
                              leading=11, textColor=TEXT_MUTED,
                              alignment=TA_CENTER, spaceAfter=4),
    "callout": ParagraphStyle("Callout", fontName="Calibri", fontSize=10,
                              leading=15.5, textColor=TEXT_PRIMARY),
    "th": ParagraphStyle("TH", fontName="Calibri", fontSize=10, leading=13,
                         textColor=colors.white, alignment=TA_LEFT),
    "td": ParagraphStyle("TD", fontName="Calibri", fontSize=9.5, leading=13,
                         textColor=TEXT_PRIMARY, alignment=TA_LEFT),
    "toc_title": ParagraphStyle("TocTitle", fontName="Calibri", fontSize=20,
                                leading=25, textColor=TEXT_PRIMARY,
                                spaceAfter=10),
}

story = []


def heading(text, level=0):
    key = "h_%s" % hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    p = Paragraph('<a name="%s"/><b>%s</b>' % (key, text),
                  S["h1"] if level == 0 else S["h2"])
    p.bookmark_name = text
    p.bookmark_level = level
    p.bookmark_text = text
    p.bookmark_key = key
    return p


def h1(text):
    return [CondPageBreak(H1_ORPHAN), heading(text, 0),
            HRFlowable(width="100%", thickness=1.6, color=ACCENT,
                       spaceBefore=0, spaceAfter=10)]


def h2(text):
    return [CondPageBreak(H1_ORPHAN * 0.6), heading(text, 1)]


def body(text):
    return Paragraph(text, S["body"])


def bullets(items):
    return [Paragraph("•  " + it, S["bullet"]) for it in items]


FIG_N = [0]


def fig(name, caption, max_h=280):
    path = os.path.join(IMG, name)
    pil = PILImage.open(path)
    ow, oh = pil.size
    ratio = min(AVAIL_W / ow, max_h / oh)
    img = Image(path, width=ow * ratio, height=oh * ratio)
    frame = Table([[img]], colWidths=[ow * ratio + 10])
    frame.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    FIG_N[0] += 1
    return [Spacer(1, 6),
            KeepTogether([frame, Spacer(1, 5),
                          Paragraph("Figure %d — %s" % (FIG_N[0], caption),
                                    S["caption"])]),
            Spacer(1, 6)]


def callout(text, title="Bon à savoir"):
    box = Table([[Paragraph("<b>%s.</b>  %s" % (title, text), S["callout"])]],
                colWidths=[AVAIL_W - 8])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TABLE_STRIPE),
        ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [Spacer(1, 4), KeepTogether(box), Spacer(1, 8)]


def table(headers, rows, ratios):
    widths = [r * AVAIL_W for r in ratios]
    data = [[Paragraph("<b>%s</b>" % h, S["th"]) for h in headers]]
    for row in rows:
        data.append([Paragraph(c, S["td"]) for c in row])
    t = Table(data, colWidths=widths, hAlign="CENTER", repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), ACCENT),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
             ("LEFTPADDING", (0, 0), (-1, -1), 7),
             ("RIGHTPADDING", (0, 0), (-1, -1), 7),
             ("TOPPADDING", (0, 0), (-1, -1), 5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), TABLE_STRIPE))
    t.setStyle(TableStyle(style))
    return [Spacer(1, 10), t, Spacer(1, 12)]


# ---- Sommaire ----
story.append(Paragraph("<b>Sommaire</b>", S["toc_title"]))
story.append(HRFlowable(width="100%", thickness=1.6, color=ACCENT,
                        spaceBefore=0, spaceAfter=12))
toc = TableOfContents()
toc.levelStyles = [
    ParagraphStyle("TOC1", fontName="Calibri", fontSize=11, leading=14.5,
                   leftIndent=14, firstLineIndent=-14, spaceBefore=2,
                   textColor=TEXT_PRIMARY),
    ParagraphStyle("TOC2", fontName="Calibri", fontSize=9.5, leading=12.5,
                   leftIndent=32, firstLineIndent=-14, textColor=TEXT_MUTED),
]
story.append(toc)
story.append(PageBreak())

story.extend(h1("1.  Introduction"))
story.append(body(
    "<b>Palworld Server Manager</b> est une application Windows qui gère ton "
    "serveur Palworld dédié privé : démarrer et arrêter le serveur, surveiller "
    "les joueurs, appliquer les mises à jour, sauvegarder le monde, programmer "
    "des redémarrages, et offrir des cadeaux (or, objets, Pals) directement "
    "dans la sauvegarde — sans aucun mod."))
story.append(body(
    "Ce guide explique chaque page de l'application avec des captures "
    "d'écran réelles. L'installation du serveur (SteamCMD + serveur dédié) est "
    "décrite pas à pas dans <b>docs/SETUP.md</b> — commence par là si tu "
    "démarres de zéro. Le serveur lui-même continue de tourner même quand "
    "l'application est fermée : elle sert à le piloter, pas à le faire "
    "tourner."))

story.extend(h1("2.  Prérequis"))
story.extend(bullets([
    "<b>Windows 10 ou 11 (64 bits)</b>. Il n'existe pas de serveur dédié "
    "Palworld pour macOS : héberge sur un PC Windows.",
    "<b>Le serveur dédié</b> installé via SteamCMD dans <dossier>\\server "
    "(voir docs/SETUP.md, deux commandes).",
    "<b>L'application</b> : PalworldControl.exe (fourni) ou compilée depuis "
    "la source (Python + requirements.txt).",
    "<b>Environ 10 Go d'espace disque</b> pour le serveur, 4 Go de RAM "
    "libres, et un PC qui reste allumé quand tes amis jouent.",
    "<b>Réseau</b> : port UDP 8211 ouvert dans le pare-feu Windows (bouton "
    "dans Maintenance) et redirigé dans ta box pour l'accès depuis Internet.",
]))

story.extend(h1("3.  Premier lancement"))
story.append(body(
    "Au double-clic de PalworldControl.exe, l'application vérifie "
    "l'installation et s'ouvre sur la page Serveur avec une liste de "
    "configuration guidée : installer le serveur, ouvrir le pare-feu, "
    "rediriger le port. L'option « Démarrer l'appli avec Windows » "
    "(Planification) la lance à chaque allumage du PC, et le serveur peut "
    "démarrer automatiquement avec elle."))
story.extend(fig("premiere_fois.png",
                 "La page Serveur au premier lancement (thème clair) : la "
                 "liste de configuration guide les étapes restantes."))
story.extend(h2("3.1  L'icône près de l'horloque (tray)"))
story.append(body(
    "Fermer la fenêtre avec le bouton X ne quitte pas l'application : elle se "
    "réduit près de l'horloge et continue de surveiller le serveur "
    "(redémarrages programmés, annonces, cadeaux planifiés…). Un double-clic "
    "sur son icône rouvre la fenêtre. Le bouton <b>« Éteindre l'appli »</b> "
    "en bas de la barre latérale la ferme vraiment ; le serveur, lui, "
    "continue de tourner."))
story.extend(callout(
    "si tu relances l'application alors qu'elle tourne déjà (visible ou "
    "réduite), un message te prévient : elle refuse de se lancer deux fois.",
    "Double lancement"))

story.extend(h1("4.  Tour de l'interface"))
story.append(body(
    "La fenêtre s'organise autour d'une barre latérale et de sept pages. En "
    "haut à droite : pastille d'état du serveur (vert = en ligne), sélecteur "
    "de thème sombre/clair, et badge orange « Mise à jour dispo » le cas "
    "échéant."))
story.extend(fig("serveur.png",
                 "La page Serveur et la barre latérale : pages, état en "
                 "direct, version et bouton Éteindre l'appli."))
story.extend(bullets([
    "<b>Barre latérale</b> — les sept pages (Ctrl+1 à Ctrl+7), point d'état, "
    "version, bouton d'extinction complète.",
    "<b>Barre du haut</b> — titre de la page, pastille d'état, thème.",
    "<b>Palette de commandes (Ctrl+K)</b> — lance n'importe quelle action "
    "depuis une boîte de recherche.",
    "<b>Aide (F1)</b> — la liste des raccourcis clavier.",
]))

story.extend(h1("5.  La page Serveur"))
story.append(body(
    "C'est la page de pilotage quotidienne : bandeau d'état, joueurs en "
    "ligne, boutons Démarrer / Arrêter / Redémarrer, et la carte d'invitation "
    "avec ton adresse (IP publique, adresse locale, et QR code à partager)."))
story.extend(h2("5.1  Joueurs et actions en direct"))
story.extend(bullets([
    "<b>Joueurs en ligne</b> — liste en continu, avatars Steam (avec une "
    "clé API Steam renseignée dans Préférences) et surnoms personnalisés.",
    "<b>Annoncer</b> — message affiché à tous les joueurs ; des annonces "
    "programmées peuvent partir automatiquement à des heures choisies.",
    "<b>Exclure / Bannir</b> — éjecter un joueur, temporairement ou "
    "définitivement.",
    "<b>Sauvegarder</b> — sauvegarde immédiate du monde.",
]))
story.extend(h2("5.2  Activité de la guilde"))
story.append(body(
    "Temps de jeu par joueur avec frise des sessions, inventaires (or et "
    "objets principaux), carte de guilde exportable en image, et actualités "
    "Palworld officielles. Un récapitulatif hebdomadaire peut être envoyé "
    "automatiquement sur Discord. La carte des bases affiche aussi les "
    "positions des joueurs, rafraîchies toutes les 75 secondes pendant "
    "que le serveur tourne."))
story.extend(h2("5.3  Cadeaux et événements"))
story.append(body(
    "La carte « Cadeaux et événements » ouvre l'assistant visuel du "
    "chapitre 12 et permet de programmer des cadeaux quotidiens "
    "automatiques. Les événements en un clic — Nuit de raid (un Pal boss "
    "pour toute la guilde), Pluie d'or, Largage de butin — lancent la "
    "fête en deux clics."))

story.extend(h1("6.  La page Réglages"))
story.append(body(
    "Toutes les options du monde Palworld, en français clair : difficulté, "
    "XP, taux de capture, morts, PvP, guildes, bases, nombre de Pals par "
    "base, crossplay… Chaque sauvegarde propose un redémarrage immédiat : "
    "l'application arrête le serveur <b>avant</b> d'écrire les réglages (le "
    "jeu réécrit son fichier à l'arrêt — c'est la seule méthode fiable), "
    "puis le relance. Si tu refuses le redémarrage, la modification est "
    "mise en file et appliquée au prochain démarrage du serveur."))
story.extend(fig("reglages.png",
                 "La page Réglages : les options regroupées par thème, avec "
                 "recherche et profils."))
story.extend(h2("6.1  Profils de réglages"))
story.append(body(
    "Les profils sauvegardent des jeux de réglages complets — par exemple "
    "« Normal » en semaine et « Week-end fou » (XP double, captures "
    "faciles) — et les presets rapides (paisible / normal / hardcore / PvP) "
    "changent les règles essentielles en un clic."))

story.extend(h1("7.  La page Planification"))
story.extend(bullets([
    "<b>Mode de fonctionnement</b> — toujours actif (24/7) ou fenêtre "
    "horaire (ex. 18 h – minuit).",
    "<b>Redémarrage quotidien</b> — conseillé (05 h par défaut) : vide la "
    "mémoire et évite les lags.",
    "<b>Chien de garde</b> — relance le serveur après un plantage et "
    "s'arrête proprement en cas de plantages en boucle, avec diagnostic.",
    "<b>Démarrage automatique</b> — serveur lancé dès l'ouverture de "
    "l'application, et application lancée avec Windows.",
]))
story.extend(fig("planification.png",
                 "La page Planification : mode de fonctionnement, redémarrage "
                 "quotidien et chien de garde."))

story.extend(h1("8.  La page Maintenance"))
story.extend(h2("8.1  Mise à jour du serveur"))
story.append(body(
    "Le bouton de mise à jour passe par SteamCMD : arrêt du serveur, "
    "téléchargement de la dernière version, vérification des fichiers, "
    "relance — avec journal en direct. Le badge orange apparaît "
    "automatiquement quand une nouvelle version est publiée."))
story.extend(h2("8.2  Sauvegardes"))
story.append(body(
    "Sauvegardes zip horodatées, listées avec leur taille ; clic droit pour "
    "<b>Restaurer</b>, <b>Vérifier</b> (contrôle d'intégrité) ou "
    "<b>Supprimer</b>. Une sauvegarde automatique a lieu avant chaque "
    "opération risquée (mise à jour, cadeau, réglages sensibles), et une "
    "copie externe peut être mirrorée vers un autre disque."))
story.extend(fig("maintenance.png",
                 "La page Maintenance : mise à jour SteamCMD, sauvegardes et "
                 "correctifs Windows."))
story.extend(h2("8.3  Réparation et correctifs Windows"))
story.append(body(
    "En cas de crash, l'application analyse les journaux et propose la cause "
    "probable avec la marche à suivre. « Appliquer les correctifs Windows » "
    "ouvre le port pare-feu UDP 8211 et empêche le PC de s'endormir "
    "(confirmation administrateur requise)."))

story.extend(h1("9.  La page Préférences"))
story.extend(bullets([
    "<b>Apparence</b> — thème sombre/clair, couleur d'accentuation, langue "
    "français/anglais.",
    "<b>Discord</b> — webhook pour recevoir les annonces (démarrages, mises "
    "à jour, cadeaux, récapé hebdomadaire) avec bouton de test.",
    "<b>Rotation du mot de passe</b> — changement automatique du mot de "
    "passe du serveur (jour/semaine/mois) envoyé sur Discord.",
    "<b>Clé API Steam</b> — gratuite sur steamcommunity.com/dev/apikey "
    "(domaine : localhost), sert aux avatars des joueurs.",
    "<b>Trophées</b> — l'étagère célèbre tes exploits d'hébergeur.",
    "<b>Page d'état téléphone</b> — une page web protégée par jeton pour "
    "suivre l'état du serveur depuis un téléphone (même Wi-Fi).",
    "<b>Exporter / Importer</b> — sauvegarde de toute la configuration.",
]))
story.extend(fig("preferences.png",
                 "La page Préférences : apparence, langue, Discord et "
                 "trophées."))

story.extend(h1("10.  La page Console"))
story.append(body(
    "La sortie en direct du serveur : connexions, avertissements, erreurs — "
    "avec surlignage des lignes d'erreur. En cas de souci, copie les "
    "dernières lignes : c'est la première information utile pour un "
    "diagnostic."))
story.extend(fig("console.png", "La page Console : la sortie live du serveur."))

story.extend(h1("11.  La page Statistiques"))
story.append(body(
    "Trois tableaux de bord résument la vie du serveur : l'activité par "
    "heure (quand tes amis jouent, sur 7 jours), le pic de joueurs par "
    "jour (14 jours), et la fiabilité — pourcentage de disponibilité "
    "hebdomadaire et plus longue série sans interruption. Les données "
    "s'écrivent toutes seules pendant que l'appli tourne."))
story.extend(fig("stats.png", "La page Statistiques : activité, pics et "
                 "fiabilité."))

story.extend(h1("12.  Offrir des cadeaux (or, objets, Pals)"))
story.append(body(
    "L'assistant visuel écrit des cadeaux directement dans la sauvegarde du "
    "monde, sans mod : de l'or, plus de 1 100 objets (vraies icônes du jeu, "
    "noms français) et près de 600 Pals (illustrations officielles). À la "
    "première ouverture, l'application télécharge les visuels (~90 Mo, une "
    "seule fois) ; ensuite tout fonctionne hors ligne."))
story.extend(h2("11.1  L'assistant en quatre gestes"))
story.extend(bullets([
    "<b>Destinataire</b> — un joueur précis ou toute la guilde.",
    "<b>Cherche et clique</b> — onglets Pals / Objets, recherche par nom "
    "(français ou identifiant) ; les tuiles cliquées rejoignent le panier.",
    "<b>Règle les montants</b> — niveau d'un Pal, nombre de copies "
    "(jusqu'à 10 par espèce), quantité d'un objet, montant d'or.",
    "<b>« Offrir maintenant »</b> — sauvegarde de sécurité, arrêt du "
    "serveur environ une minute le temps d'écrire le cadeau, relance, puis "
    "annonce aux joueurs (et sur Discord si configuré).",
]))
story.extend(fig("cadeaux_pals.png",
                 "L'assistant de cadeaux, onglet Pals : illustrations "
                 "officielles et panier à droite.", max_h=270))
story.extend(fig("cadeaux_objets.png",
                 "L'onglet Objets : les vraies icônes du jeu, noms "
                 "français.", max_h=270))
story.extend(fig("cadeaux_panier.png",
                 "Le panier rempli : un Pal niveau 30 et 10 Sphères de Pal.",
                 max_h=270))
story.extend(callout(
    "les cadeaux ne suppriment rien : ils sont ajoutés à la fin de "
    "l'inventaire / de la boîte du joueur. En cas d'échec d'écriture, le "
    "monde est automatiquement restauré depuis la sauvegarde d'avant-cadeau.",
    "En toute sécurité"))
story.extend(h2("11.2  Cadeaux programmés"))
story.append(body(
    "Programme un cadeau quotidien : heure, or, objets (format "
    "« PalSphere x20, Arrow x100 ») et un Pal — chaque jour, tous les "
    "membres de la guilde le reçoivent automatiquement."))

story.extend(h1("13.  Raccourcis clavier"))
story.extend(table(
    ["Raccourci", "Action"],
    [["Ctrl + 1 … Ctrl + 7", "Aller directement à une page"],
     ["Ctrl + K", "Palette de commandes"],
     ["F1 ou touche ?", "Aide des raccourcis"],
     ["Double-clic sur l'icône du tray", "Rouvrir la fenêtre réduite"],
     ["Bouton X de la fenêtre", "Réduire dans le tray (l'appli continue)"],
     ["« Éteindre l'appli » (barre latérale)", "Fermer totalement "
      "l'application"]],
    [0.42, 0.58]))

story.extend(h1("14.  FAQ et dépannage"))
faq = [
    ("Mes amis n'arrivent pas à rejoindre.",
     "Vérifie dans l'ordre : pastille verte dans l'appli ; correctif "
     "pare-feu appliqué (Maintenance) ; redirection UDP 8211 vers l'IP "
     "locale du PC dans ta box ; partage l'adresse exacte affichée sur la "
     "page Serveur. Les joueurs console (Xbox/PS5) passent par la liste "
     "des serveurs communautaires du jeu : ils cherchent le nom du "
     "serveur et entrent le mot de passe."),
    ("Un badge orange « Mise à jour dispo » est apparu.",
     "Une nouvelle version du jeu est sortie : Maintenance → Mettre à "
     "jour, quand tes joueurs sont déconnectés."),
    ("J'ai double-cliqué mais l'appli ne s'ouvre pas.",
     "Elle tourne déjà, réduite près de l'horloge (un message te l'indique "
     "au second lancement). Double-clique son icône dans le tray."),
    ("Un cadeau a échoué.",
     "Rien n'est perdu : le monde est restauré automatiquement depuis la "
     "copie d'avant-cadeau. Relance simplement l'assistant."),
    ("Un réglage ne semble pas appliqué en jeu.",
     "Les réglages ne sont lus par le serveur qu'au démarrage : "
     "enregistre puis accepte le redémarrage proposé (ou vérifie la "
     "mention « appliqué au prochain démarrage »)."),
    ("Où sont mes sauvegardes ?",
     "Dans <dossier>\\backups (zip horodatés), restaurables d'un clic "
     "depuis la page Maintenance."),
]
for q, a in faq:
    story.extend([CondPageBreak(70),
                  KeepTogether([Paragraph("<b>%s</b>" % q, S["h3"]),
                                Paragraph(a, S["body"])])])

story.extend(h1("15.  Annexe : emplacements utiles"))
story.extend(table(
    ["Élément", "Emplacement / valeur"],
    [["Application", "<dossier d'installation>\\PalworldControl.exe"],
     ["Serveur dédié", "<dossier>\\server (installé via SteamCMD, app 2394010)"],
     ["Réglages du serveur", "<dossier>\\server\\Pal\\Saved\\Config\\"
      "WindowsServer\\PalWorldSettings.ini"],
     ["Sauvegardes zip", "<dossier>\\backups (horodatées)"],
     ["Configuration de l'appli", "%LOCALAPPDATA%\\PalworldControl"],
     ["Visuels de l'assistant cadeaux", "%LOCALAPPDATA%\\PalworldControl\\"
      "icons (téléchargés à la première ouverture)"],
     ["Port de jeu", "UDP 8211 (pare-feu + redirection box)"],
     ["Console d'administration", "RCON 25575, mot de passe admin dans "
      "Réglages → Identité et accès"]],
    [0.34, 0.66]))
story.append(Spacer(1, 10))
story.append(body(
    "Manuel de la version 1.1 — septembre 2026. Outil communautaire non "
    "affilié à Pocketpair. Bon jeu, et prends soin de tes Pals."))

doc = TocDocTemplate(
    OUT, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
    topMargin=2.1 * cm, bottomMargin=1.9 * cm,
    title=DOC_TITLE, author="Z.ai", creator="Z.ai",
    subject="Guide complet de l'application Palworld Server Manager")
doc.multiBuild(story, onFirstPage=on_page, onLaterPages=on_page)
print("body OK")

# ---- fusion couverture + corps ----
from pypdf import PdfReader, PdfWriter, Transformation  # noqa: E402

A4_W, A4_H = 595.28, 841.89


def normalize(page):
    w, h = float(page.mediabox.width), float(page.mediabox.height)
    if abs(w - A4_W) > 0.1 or abs(h - A4_H) > 0.1:
        page.add_transformation(Transformation().scale(A4_W / w, A4_H / h))
        page.mediabox.lower_left = (0, 0)
        page.mediabox.upper_right = (A4_W, A4_H)
    return page


writer = PdfWriter()
writer.add_page(normalize(PdfReader(COVER).pages[0]))
for p in PdfReader(OUT).pages:
    writer.add_page(normalize(p))
writer.add_metadata({"/Title": DOC_TITLE, "/Author": "Z.ai",
                     "/Creator": "Z.ai",
                     "/Subject": "Guide complet - Palworld Server Manager"})
with open(FINAL, "wb") as f:
    writer.write(f)
print("final:", FINAL, len(writer.pages), "pages")
