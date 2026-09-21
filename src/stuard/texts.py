"""User-facing texts (Slovak). Edit freely — keep the {placeholders}."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stuard.config import AppConfig

LABELS: dict[str, str] = {
    "unverified": "neoverený",
    "applicant": "Uchádzač",
    "student": "Študent",
    "former_student": "Bývalý študent",
    "alumni": "Absolvent",
    "teacher": "Vyučujúci",
}
METHOD_LABELS: dict[str, str] = {
    "sso": "prihlásenie cez STU (idp.stuba.sk)",
    "microsoft": "prihlásenie cez Microsoft 365 (STU)",
    "manual": "manuálne overenie moderátorom",
    "mod": "nastavené moderátorom",
}
VIA_LABELS: dict[str, str] = {
    "saml": "idp.stuba.sk",
    "microsoft": "Microsoft 365 (STU)",
    "email": "e-mailový kód (@stuba.sk)",
}

# ------------------------------------------------------------------ general
NOT_IN_GUILD = "Tento príkaz funguje iba na serveri."
NO_PERMISSION = "Na toto nemáš oprávnenie."
GENERIC_ERROR = "Niečo sa pokazilo. Skús to znova neskôr alebo kontaktuj moderátorov."
CANCEL = "Zrušiť"
CANCELLED = "Zrušené."
YES = "áno"
NO = "nie"
STATE_ON = "zapnuté"
STATE_OFF = "vypnuté"
STATE_DEFAULT = "podľa config.yaml"

# ------------------------------------------------------------------ verification
VERIFY_INTRO = (
    "**Overenie – MTF STU**\n"
    "Heslo zadávaš iba na stránke STU alebo Microsoftu – bot ho nikdy nevidí. "
    "Discord ťa najprv požiada o potvrdenie, že si to naozaj ty."
)
VERIFY_OPTION_STU = "• **Prihlásiť sa cez STU** – AIS login a heslo na idp.stuba.sk (študenti a zamestnanci)."
VERIFY_OPTION_MICROSOFT = (
    "• **Prihlásiť sa cez Microsoft 365** – školské konto @stuba.sk. Ak Microsoft napíše, že je potrebné "
    "schválenie správcu, STU to nepovoľuje – použi manuálne overenie."
)
VERIFY_OPTION_EMAIL = (
    "• **E-mailom** – príkaz `/verify-email` pošle jednorazový kód na tvoj školský e-mail "
    "(@stuba.sk), ktorý potvrdíš príkazom `/verify-code` (pre študentov)."
)
VERIFY_OPTION_MANUAL = "• **Manuálne** – príkaz `/verify-manual` so snímkou z UIS (napr. uchádzači)."
VERIFY_LINK_FOOTER = "Odkazy platia {minutes} minút, fungujú iba raz a sú len pre teba. **Nikomu ich neposielaj.**"
VERIFY_NO_LINK_LOGIN = "Automatické prihlásenie (STU / Microsoft) zatiaľ nie je zapnuté. Použi jednu z týchto možností:"
VERIFY_LINK_BUTTON = "Prihlásiť sa cez STU"
VERIFY_MICROSOFT_BUTTON = "Prihlásiť sa cez Microsoft 365"
VERIFY_RATE_LIMITED = "Príliš veľa pokusov. Skús to znova o {minutes} min."
VERIFY_DISABLED = "Overovanie je momentálne vypnuté. Kontaktuj moderátorov."
VERIFY_PANEL_TITLE = "Overenie – MTF STU"
VERIFY_PANEL_INTRO = "Pre prístup na server sa over. K dispozícii máš tieto možnosti:"
VERIFY_PANEL_FOOTER = (
    "Heslo zadávaš iba na stránke STU alebo Microsoftu – bot ho nikdy nevidí ani neukladá.\n"
    "Klikni na tlačidlo nižšie alebo použi uvedený príkaz."
)
VERIFY_PANEL_NONE = "Overovanie je momentálne vypnuté. Kontaktuj moderátorov."
VERIFY_PANEL_BUTTON = "Overiť sa"
MANUAL_PANEL_BUTTON = "Manuálne overenie"

MANUAL_INSTRUCTIONS = (
    "**Manuálne overenie**\n"
    "1. Študenti a vyučujúci: prihlás sa na https://is.stuba.sk a otvor *Portál študenta* "
    "alebo *Portál zamestnanca*. Uchádzači: otvor svoju e-prihlášku, kde je vidieť stav prihlášky.\n"
    "2. Sprav snímku obrazovky, na ktorej je vidieť tvoje meno a stav štúdia / prihlášky / pracovný pomer.\n"
    "3. **Začierni rodné číslo, dátum narodenia a adresu.** Nikdy nikomu neposielaj heslo.\n"
    "4. Použi príkaz `/verify-manual`, vyber rolu a pripoj snímku."
)
VERIFY_USE_MANUAL = "Automatické prihlásenie zatiaľ nie je zapnuté.\n\n" + MANUAL_INSTRUCTIONS
MANUAL_DISABLED = "Manuálne overenie teraz nie je dostupné – použi /verify."
MANUAL_BAD_FILE = "Pripoj obrázok vo formáte PNG, JPEG alebo WEBP s veľkosťou do {mb} MB."
MANUAL_ALREADY_PENDING = "Tvoja žiadosť už čaká na moderátora. Vydrž, prosím."
MANUAL_ALREADY_VERIFIED = "Už máš rolu **{role}**. Ak sa niečo zmenilo, kontaktuj moderátorov."
MANUAL_COOLDOWN = "Tvoja posledná žiadosť bola zamietnutá. Novú môžeš poslať približne o {hours} h."
MANUAL_TOO_MANY = "Poslal si príliš veľa žiadostí. Kontaktuj moderátorov."
MANUAL_NOT_CONFIGURED = "Kanál pre moderátorov nie je nastavený. Kontaktuj adminov servera."
MANUAL_SUBMITTED = (
    "Žiadosť odoslaná ✅ Moderátor ju skontroluje a výsledok ti pošlem do súkromnej správy.\n"
    "Snímka je viditeľná iba moderátorom a po rozhodnutí sa vymaže."
)

# ------------------------------------------------------------------ email-code verification
EMAIL_SUBJECT = "STUard – overovací kód"
EMAIL_BODY = (
    "Ahoj,\n\ntvoj overovací kód pre Discord server MTF STU je:\n\n    {code}\n\n"
    "Zadaj ho na Discorde príkazom /verify-code. Platí {minutes} minút.\n"
    "Ak si o kód nežiadal(a), túto správu ignoruj."
)
EMAIL_DISABLED = "Overenie e-mailom nie je zapnuté. Použi /verify alebo /verify-manual."
EMAIL_NOT_CONFIGURED = "Odosielanie e-mailov nie je nastavené. Kontaktuj adminov servera."
EMAIL_BAD_LOGIN = "Zadaj svoj školský login (napr. `xnovak`) alebo číslo AIS ID."
EMAIL_NOT_FOUND = "Tento login sa v systéme STU nenašiel. Skontroluj ho, alebo použi /verify-manual."
EMAIL_REJECTED = "Podľa STU nie si študentom MTF. Ak ide o omyl, použi /verify-manual alebo kontaktuj moderátorov."
EMAIL_SENT = (
    "Kód som poslal na **{email}** ✅ (platí {minutes} min).\n"
    "Školský e-mail si otvoríš na <https://webmail.stuba.sk> (nie v AIS/UIS).\n"
    "Kód potom zadaj príkazom **/verify-code**."
)
EMAIL_SEND_FAILED = "E-mail sa nepodarilo odoslať. Skús to o chvíľu znova alebo použi /verify-manual."
EMAIL_NO_PENDING = "Najprv si vyžiadaj kód príkazom /verify-email."
EMAIL_EXPIRED = "Kód vypršal. Vyžiadaj si nový príkazom /verify-email."
EMAIL_WRONG_CODE = "Nesprávny kód. Zostáva pokusov: {left}."
EMAIL_TOO_MANY = "Priveľa pokusov. Vyžiadaj si nový kód príkazom /verify-email."
EMAIL_CONFLICT = "Toto školské konto je už prepojené s iným Discord účtom. Ak ide o omyl, kontaktuj moderátorov."
EMAIL_TOMBSTONED = "Toto školské konto bolo nedávno odpojené. Skús to neskôr alebo kontaktuj moderátorov."
EMAIL_VERIFIED = "Overené ✅ Máš rolu **Študent**. Program a ročník si nastav cez /profile."
EMAIL_TEACHER_PENDING = "Overené ✅ Žiadosť o rolu **Vyučujúci** dostali moderátori, výsledok ti pošlem správou."
EMAIL_REVIEW_PENDING = "E-mail overený ✅ Rolu ešte potvrdí moderátor, výsledok ti pošlem správou."

# ------------------------------------------------------------------ reviews (moderators)
REVIEW_TITLES = {
    "manual": "Manuálne overenie (snímka z UIS)",
    "sso_teacher": "Žiadosť o rolu Vyučujúci (prihlásenie úspešné)",
    "sso_status": "Prihlásenie úspešné – rolu treba potvrdiť",
}
REVIEW_FIELD_MEMBER = "Člen"
REVIEW_FIELD_ACCOUNT_AGE = "Discord účet vytvorený"
REVIEW_FIELD_CLAIMED = "Žiada rolu"
REVIEW_FIELD_SUGGESTION = "Návrh"
REVIEW_FIELD_NOTE = "Poznámka"
REVIEW_FIELD_AFFILIATIONS = "Príslušnosť podľa idp.stuba.sk"
REVIEW_FIELD_EMPLOYEE_TYPE = "Typ konta v Microsoft 365"
REVIEW_FIELD_VIA = "Spôsob prihlásenia"
REVIEW_FIELD_LOGIN = "Školský login"
REVIEW_FOOTER = "Žiadosť #{id} · po rozhodnutí sa táto správa vymaže"
REVIEW_APPROVE = "Schváliť: {role}"
REVIEW_REJECT = "Zamietnuť"
REVIEW_REJECT_MODAL_TITLE = "Zamietnuť žiadosť"
REVIEW_REJECT_REASON = "Dôvod (pošle sa členovi)"
REVIEW_ALREADY_DECIDED = "Túto žiadosť už niekto vybavil."
REVIEW_SELF = "O vlastnej žiadosti rozhodovať nemôžeš."
REVIEW_ACTION_INVALID = "Táto akcia sa na túto žiadosť nehodí."
REVIEW_APPROVED = "Schválené: {member} → **{role}**."
REVIEW_REJECTED = "Zamietnuté: {member}."

DM_APPROVED = "✅ Tvoje overenie na serveri **{guild}** bolo schválené. Rola: **{role}**."
DM_APPROVED_STUDENT_HINT = "\nNastav si študijný program a ročník príkazom **/profile**."
DM_REJECTED = "❌ Tvoja žiadosť o overenie na serveri **{guild}** bola zamietnutá.\nDôvod: {reason}"
DM_EXPIRED = "⌛ Tvoja žiadosť o overenie na serveri **{guild}** vypršala bez rozhodnutia. Pošli, prosím, novú."

# ------------------------------------------------------------------ yearly re-verification
REVERIFY_REMINDER = (
    "📅 Ahoj! Na serveri **{guild}** treba obnoviť overenie do **{deadline}**. Použi príkaz /verify.\n"
    "Po overení si v /profile aktualizuj ročník."
)
REVERIFY_EXPIRED_DM = (
    "Tvoje overenie na serveri **{guild}** vypršalo, preto máš teraz stav **{status}**. Obnovíš ho príkazom /verify."
)

# ------------------------------------------------------------------ profile / study selection
PROFILE_TITLE = "Tvoj profil"
PROFILE_STATUS = "Stav"
PROFILE_TEACHER = "Vyučujúci"
PROFILE_METHOD = "Spôsob overenia"
PROFILE_VERIFIED_AT = "Posledné overenie"
PROFILE_VALID_UNTIL = "Treba obnoviť do"
PROFILE_STUDY = "Štúdium"
PROFILE_UIS_LINKED = "Prepojené školské konto"
PROFILE_NO_STUDY = "nenastavené"
PROFILE_UNVERIFIED = "Zatiaľ nie si overený. Použi /verify."

STUDY_NOT_ALLOWED = "Študijný program a ročník si môžu nastaviť iba overení študenti."
STUDY_PICK_DEGREE = "Vyber stupeň štúdia"
STUDY_PICK_PROGRAMME = "Vyber študijný program"
STUDY_PICK_YEAR = "Vyber ročník"
STUDY_YEAR = "{year}. ročník"
STUDY_SAVE = "Uložiť"
STUDY_CLEAR = "Vymazať výber"
STUDY_EDITOR = "**Nastavenie štúdia**\n{summary}"
STUDY_SAVED = "Uložené ✅ {summary}"
STUDY_CLEARED = "Výber štúdia bol vymazaný."
STUDY_INCOMPLETE = "vyber stupeň, program aj ročník"
STUDY_PANEL_TITLE = "Študijný program a ročník"
STUDY_PANEL_TEXT = (
    "Klikni na tlačidlo a vyber si stupeň, študijný program a ročník.\n"
    "Podľa výberu uvidíš kanály svojho programu a ročníka. Zmeniť to môžeš kedykoľvek cez /profile."
)
STUDY_PANEL_BUTTON = "Nastaviť štúdium"

# ------------------------------------------------------------------ moderation
MOD_STATUS_DONE = "{member}: stav nastavený na **{status}**."
MOD_TEACHER_ADDED = "{member} má teraz rolu **Vyučujúci**."
MOD_TEACHER_REMOVED = "{member} už nemá rolu **Vyučujúci**."
MOD_INFO_TITLE = "Člen: {name}"
MOD_UNLINKED = "Školské konto člena {member} bolo odpojené."
MOD_NOT_LINKED = "{member} nemá prepojené školské konto."
MOD_NOT_VERIFIED = "{member} nie je overený."
MOD_REVERIFY_DONE = "{member} musí obnoviť overenie do {deadline}."
MOD_REVERIFY_DM = "Moderátori servera **{guild}** ťa žiadajú o obnovenie overenia do **{deadline}**. Použi /verify."
MOD_REQUESTS_EMPTY = "Žiadne čakajúce žiadosti."
MOD_REQUESTS_TITLE = "Čakajúce žiadosti"
MOD_LOOKUP_FOUND = "Toto konto je prepojené s {member}."
MOD_LOOKUP_NONE = "Toto konto nie je prepojené so žiadnym členom."
MOD_TARGET_BOT = "Toto s botom nejde."

# ------------------------------------------------------------------ setup / admin
SETUP_CHECK_TITLE = "Kontrola nastavenia STUard"
SETUP_ROLES_OK = "✅ Roly v poriadku: {n}"
SETUP_ROLES_ADOPTED = "🔗 Prevzaté existujúce roly: {names}"
SETUP_ROLES_CREATED = "🆕 Vytvorené roly: {names}"
SETUP_ROLES_ADOPTABLE = "🔗 Existujúce roly, ktoré `/setup roles` prepojí (nevytvorí duplikáty): {names}"
SETUP_ROLES_MISSING = "❌ Chýbajúce roly (spusti /setup roles): {names}"
SETUP_UNVERIFIED_HOLDERS = (
    "⚠️ {n} členov má študijné roly (napr. 1-BC), ale nie sú overení ako študenti. "
    "Bot im ich sám neodoberie – odober ich ručne alebo ich požiadaj o /verify."
)
SETUP_ROLES_TOO_HIGH = "⚠️ Tieto roly sú nad rolou bota – presuň rolu bota vyššie: {names}"
SETUP_PERM_MISSING = "⚠️ Bot nemá oprávnenie **{perm}**."
SETUP_CHANNEL_MISSING = "⚠️ Kanál `channels.{name}` nie je nastavený alebo doň bot nevidí."
SETUP_CHANNEL_OK = "✅ Kanál `channels.{name}`: {channel}"
SETUP_SSO_STATE = "STU (idp.stuba.sk): **{state}** (config: {config}, prepínač: {override}, SAML súbory: {files})"
SETUP_MICROSOFT_STATE = "Microsoft 365: **{state}** (config: {config}, prepínač: {override}, aplikácia: {app})"
SETUP_MANUAL_STATE = "Manuálne overenie (snímka): **{state}** (režim: {mode}, prepínač: {override})"
SETUP_EMAIL_STATE = "E-mailový kód: **{state}** (config: {config}, prepínač: {override}, LDAP: {ldap})"
SETUP_SYNCED = "Slash príkazy synchronizované: {n}."
SETUP_RELOADED = "Konfigurácia znovu načítaná ✅"
SETUP_RELOAD_FAILED = "Konfigurácia je neplatná, ponechávam pôvodnú:\n```\n{error}\n```"
SETUP_PANELS_POSTED = "Panely odoslané: {names}"
SETUP_PANELS_NONE = "Najprv nastav `channels.verify` a/alebo `channels.study_panel` v config.yaml."
ADMIN_SSO_SET = "Prepínač STU prihlásenia: **{state}**. Aktuálne je prihlásenie cez idp.stuba.sk **{effective}**."
ADMIN_SSO_NO_SAML = (
    "\n⚠️ SAML súbory (kľúč, certifikát, metadáta IdP) chýbajú – SSO sa nezapne, kým ich nedoplníš a nereštartuješ bota."
)
ADMIN_MICROSOFT_SET = "Prepínač Microsoft 365: **{state}**. Aktuálne je prihlásenie cez Microsoft **{effective}**."
ADMIN_MICROSOFT_NO_APP = (
    "\n⚠️ V .env chýba MICROSOFT_CLIENT_ID alebo MICROSOFT_CLIENT_SECRET – prihlásenie cez Microsoft sa nezapne, "
    "kým ich nedoplníš a nereštartuješ bota."
)
ADMIN_EMAIL_SET = "Prepínač overenia e-mailom: **{state}**. Aktuálne je overenie e-mailom **{effective}**."
ADMIN_MANUAL_SET = (
    "Prepínač manuálneho overenia: **{state}**. Aktuálne je manuálne overenie **{effective}**.\n"
    "Keď je vypnuté, každý sa musí prihlásiť (Microsoft/STU/e-mail); manuálne zapni len keď treba overiť vyučujúceho."
)
ADMIN_REVERIFY_STATUS = (
    "Opätovné overenie: **{enabled}** · najbližší termín: **{deadline}** · "
    "členov s termínom: {count} · po termíne: {overdue}"
)
ADMIN_REVERIFY_RAN = "Hotovo – pripomienky: {reminded}, vypršané: {expired}."

# ------------------------------------------------------------------ privacy
PRIVACY_EXPORT_NOTE = "V prílohe je kópia údajov, ktoré o tebe bot uchováva."
FORGET_CONFIRM = "Naozaj chceš vymazať všetky svoje údaje? Stratíš overené roly a budeš sa musieť overiť znova.{extra}"
FORGET_TOMBSTONE = "\nTvoje školské konto sa potom {days} dní nebude dať znova prepojiť (ochrana pred zneužitím)."
FORGET_BUTTON = "Áno, vymazať moje údaje"
FORGET_DONE = "Tvoje údaje boli vymazané a overené roly odobraté."

# ------------------------------------------------------------------ web pages
WEB_SITE_TITLE = "STUard – overenie MTF STU"
WEB_MESSAGES: dict[str, tuple[str, str]] = {
    "link_invalid": ("Neplatný odkaz", "Tento odkaz je neplatný. Vráť sa na Discord a použi /verify znova."),
    "link_expired": (
        "Odkaz vypršal",
        "Odkaz už bol použitý alebo vypršal. Vráť sa na Discord a použi /verify znova.",
    ),
    "sso_disabled": ("Prihlásenie cez STU je vypnuté", "Na Discorde použi /verify-manual alebo kontaktuj moderátorov."),
    "microsoft_disabled": (
        "Prihlásenie cez Microsoft 365 je vypnuté",
        "Na Discorde použi /verify alebo /verify-manual.",
    ),
    "microsoft_consent": (
        "STU túto možnosť nepovoľuje",
        "Školské Microsoft 365 konto vyžaduje na prihlásenie do tejto aplikácie schválenie správcu STU. "
        "Na Discorde použi /verify-manual (snímka z UIS).",
    ),
    "microsoft_failed": (
        "Prihlásenie sa nepodarilo",
        "Prihlásenie cez Microsoft 365 sa nepodarilo overiť. Použi /verify znova alebo /verify-manual.",
    ),
    "rate_limited": ("Príliš veľa pokusov", "Počkaj chvíľu a skús to znova."),
    "session_missing": (
        "Chýba relácia",
        "Dokonči overenie v tom istom prehliadači, v ktorom si otvoril odkaz z Discordu. Použi /verify znova.",
    ),
    "session_mismatch": (
        "Iný prehliadač",
        "Overenie treba dokončiť v tom istom prehliadači, v ktorom si otvoril odkaz z Discordu. "
        "Ak ti odkaz niekto poslal, nepokračuj. Použi /verify znova.",
    ),
    "oauth_denied": ("Zrušené", "Prihlásenie bolo zrušené. Použi /verify znova."),
    "oauth_failed": ("Chyba Discordu", "Nepodarilo sa overiť tvoj Discord účet. Použi /verify znova."),
    "oauth_mismatch": (
        "Iný Discord účet",
        "V prehliadači si prihlásený do iného Discord účtu, než ktorý použil /verify. "
        "Odkaz na overenie nikomu neposielaj.",
    ),
    "saml_invalid": ("Prihlásenie sa nepodarilo", "Odpoveď z idp.stuba.sk sa nepodarilo overiť. Použi /verify znova."),
    "scope_invalid": ("Nepodporovaný účet", "Tento účet nepatrí STU."),
    "conflict": (
        "Účet je už prepojený",
        "Toto školské konto je už prepojené s iným Discord účtom. Ak ide o omyl, kontaktuj moderátorov.",
    ),
    "tombstoned": (
        "Dočasne zablokované",
        "Toto školské konto bolo nedávno odpojené. Skús to neskôr alebo kontaktuj moderátorov.",
    ),
    "rejected": (
        "Overenie sa nepodarilo",
        "Podľa údajov z STU nespĺňaš podmienky overenia. Ak ide o omyl, kontaktuj moderátorov.",
    ),
    "verified": ("Overenie úspešné ✅", "Si overený ako {status}. Túto stránku môžeš zavrieť a vrátiť sa na Discord."),
    "former": (
        "Overenie dokončené",
        "STU ťa momentálne neeviduje ako študenta, preto máš stav Bývalý študent. "
        "Ak ide o omyl, kontaktuj moderátorov.",
    ),
    "pending": (
        "Čaká sa na moderátora",
        "Prihlásenie bolo úspešné, rolu však musí potvrdiť moderátor. Výsledok ti pošleme na Discorde.",
    ),
    "error": ("Chyba", "Niečo sa pokazilo (kód {ref}). Skús to znova neskôr."),
    "not_found": ("Nenájdené", "Táto stránka neexistuje."),
}
WEB_TEACHER_PENDING = "Žiadosť o rolu Vyučujúci bola odoslaná moderátorom."
CONFIRM_TITLE = "Si to ty?"
CONFIRM_TEXT = "Overuješ tento Discord účet:"
CONFIRM_WARNING = "Pokračuj iba ak je to tvoj účet. Ak ti tento odkaz niekto poslal, zavri stránku."
CONFIRM_BUTTON = "Áno, pokračovať na prihlásenie"
PRIVACY_TITLE = "Ochrana osobných údajov"


def privacy_notice(cfg: AppConfig) -> list[str]:
    r = cfg.retention
    e = cfg.email
    contact = cfg.privacy_contact.strip() or "moderátori Discord servera"
    paragraphs = [
        "STUard je bot Discord servera študentov MTF STU. Overuje, že člen má konto STU, a prideľuje roly.",
        "Overenie prebieha prihlásením školským kontom Microsoft 365 alebo na idp.stuba.sk, alebo jednorazovým "
        "kódom zaslaným na školský e-mail (@stuba.sk). Pri prihlásení heslo zadávaš výhradne na stránke STU; bot "
        "ho nikdy nevidí ani neukladá. Z Microsoft 365 bot načíta prihlasovacie meno, číslo AIS ID a typ konta "
        "(napr. študent), z idp.stuba.sk identifikátor konta a typ príslušnosti.",
        "Ukladáme: Discord ID, stav overenia a jeho dátumy, jednosmerný kryptografický odtlačok (HMAC) čísla "
        "AIS ID alebo identifikátora konta – aby jedno konto nebolo možné použiť pre viac Discord účtov –, typ "
        "konta alebo príslušnosti a zvolený stupeň, program a ročník. Prihlasovacie meno, AIS ID, meno ani "
        "e-mail si neuchovávame natrvalo v čitateľnej podobe.",
        f"Pri overení e-mailovým kódom posielame kód na tvoj školský e-mail cez službu Resend "
        f"(poskytovateľ odosielania e-mailov / spracovateľ so sídlom v USA), ktorá môže záznam o odoslanom "
        f"e-maile (adresu a obsah správy) uchovávať vo svojich logoch až 30 dní. Počas overovania (kým kód "
        f"nezadáš alebo nevyprší, najviac {e.code_ttl_minutes} min) dočasne uložíme tvoj školský login, e-mail "
        "a odtlačok kódu; po overení alebo vypršaní sa tieto údaje zmažú.",
        f"Pri manuálnom overení je snímka obrazovky viditeľná iba moderátorom a po rozhodnutí sa vymaže "
        f"(najneskôr po {cfg.manual.expire_days} dňoch). Ak rolu po prihlásení cez Microsoft 365 potvrdzuje "
        "moderátor, vidí v žiadosti aj tvoj školský login a typ konta; aj táto správa sa po rozhodnutí vymaže.",
        "Účel: prístup do kanálov pre študentov, uchádzačov a vyučujúcich MTF STU. Právny základ: tvoj súhlas "
        "(overenie je dobrovoľné). Záznamy moderácie a dočasná blokácia konta po vymazaní údajov: "
        "oprávnený záujem na ochrane pred zneužitím.",
        f"Uchovávanie: počas členstva na serveri; {r.left_member_days} dní po odchode zo servera; záznamy "
        f"moderácie {r.audit_days} dní; nedokončené overenia {r.flows_hours} hodín; overovacie e-mailové kódy "
        f"do vypršania (max {e.code_ttl_minutes} min); záznamy o odoslaných e-mailoch u služby Resend do 30 dní.",
        "Tvoje práva: kópia údajov (/privacy), vymazanie (/forget-me), odvolanie súhlasu kedykoľvek, sťažnosť "
        "na Úrad na ochranu osobných údajov SR.",
        f"Kontakt: {contact}.",
    ]
    return paragraphs
