# Communication multi-canal pour Showdesk

> Document de brainstorm -- 2026-05-01
>
> Auteur : recherche Claude. Objectif : aider à prioriser une roadmap "channels"
> au-delà du widget vidéo embarqué.

---

## TL;DR

- **L'email entrant est le canal n°1 à ajouter** : forte attente côté clients,
  techniquement maîtrisé (Postmark/SES/Mailgun), peu de friction légale, clé pour
  passer d'un widget vidéo à un vrai helpdesk multi-source.
- **WhatsApp Business Cloud API** vient juste après en valeur perçue : Meta facture
  désormais au message (depuis le 1er juillet 2025), les **conversations service
  sont gratuites depuis novembre 2024**, et les 1 000 conversations service par mois
  offertes couvrent largement les early-adopters.
- **Slack Connect** est le canal "B2B SaaS" naturel pour les startups dont les
  clients vivent dans Slack -- complexité d'intégration moyenne, ROI très élevé sur
  un segment précis.
- **Instagram DM / Messenger / SMS / Teams / Discord** sont à pousser plus tard,
  une fois l'architecture conversationnelle unifiée stabilisée.
- **Le vrai chantier n'est pas "intégrer un canal"**, c'est de transformer le modèle
  `Ticket → TicketMessage` en `Conversation → Message + Channel` avec une identité
  enduser unifiée (email, phone, handle...). Faire ce refactor **une fois** avant
  d'empiler les canaux.

---

## Tableau récapitulatif

| Canal | Faisabilité technique | Coût indicatif (1 000 msgs/mois) | Complexité d'intégration | Priorité recommandée |
|---|---|---|---|---|
| **Email entrant + sortant** | Élevée -- providers matures | $15-35/mois (Postmark / Mailgun) ou ~$0,10 + endpoint SES | Moyenne (parsing + threading + rebonds) | **P0 -- premier canal à livrer** |
| **WhatsApp Business Cloud API (direct Meta)** | Bonne -- API Meta officielle | 1 000 conv. service gratuites/mois ; ensuite ~$0,005-0,02/message | Élevée (BSP, vérification numéro, templates) | **P1 -- gros impact perçu** |
| WhatsApp via Twilio / 360dialog | Très bonne (provider gère onboarding) | Twilio : +$0,005/msg ; 360dialog : $49-99/mois flat + Meta | Moyenne | P1 alternative -- recommandé si pas envie de gérer Meta direct |
| **Slack Connect** | Bonne -- API Slack solide | Gratuit côté API ; coût = effort dev | Élevée (mapping channel <-> client, threads) | **P1 -- segment B2B SaaS** |
| Instagram DM | Moyenne -- Graph API Meta | Gratuit (inclus dans WhatsApp Cloud) | Moyenne (compte Insta business + page FB liée) | P2 |
| Facebook Messenger | Moyenne | Gratuit | Moyenne (page FB requise) | P2 |
| **SMS (Twilio / Vonage)** | Élevée | ~$0,008-0,02/msg + numéro $1-15/mois | Faible techniquement, lourde côté légal/opt-in | P2 (notifications outbound) / P3 (deux-sens) |
| Microsoft Teams | Moyenne (incoming webhook = sortant only ; app Teams = lourd) | Gratuit | Élevée si app complète | P3 |
| Discord | Bonne -- bot + interactions | Gratuit | Moyenne | P3 (niche communauté) |
| Téléphone (renvoi vers item phone-support) | -- | -- | -- | hors scope ici |

---

## 1. Email -- priorité absolue

### 1.1 Pourquoi en premier

- C'est le canal de support le plus universel : tout enduser sait y répondre.
- Aucun pré-requis "business" pour le client (pas de page FB, pas de numéro WhatsApp
  vérifié, pas de Slack Connect).
- Permet de capter les tickets depuis les notifications email existantes -- aujourd'hui
  l'enduser **reçoit** un email Showdesk quand l'agent répond, mais il **ne peut pas
  y répondre** : c'est l'amélioration la plus naturelle à attaquer.
- Aligne Showdesk avec ce que tout helpdesk grand public propose (Zendesk, Freshdesk,
  HelpScout...).

### 1.2 Architecture technique

**Sortant** (déjà fait) : Showdesk envoie déjà les emails via `send_mail` /
Celery. Il faut juste enrichir les en-têtes.

**Entrant** :

1. **Provider d'inbound** : déléguer la réception MX à un service qui parse l'email
   et tape un webhook Showdesk avec le JSON propre.
   - **Postmark Inbound** (recommandé pour démarrer) : $15/mois Basic (mais inbound
     locked sur Pro à $16,50/mois ou Platform à $18/mois), 10 000 messages inclus
     transactional+inbound, parsing JSON propre, pièces jointes incluses. Voir
     [Postmark inbound webhook](https://postmarkapp.com/developer/webhooks/inbound-webhook).
   - **AWS SES Mail Manager** : $0,10 / 1 000 chunks de 256 KB + frais d'endpoint
     mensuel. Plus complexe à câbler (S3 / SNS / Lambda) mais imbattable à
     gros volume. Voir [SES pricing](https://aws.amazon.com/ses/pricing/).
   - **Mailgun Inbound Routing** : $35/mois Foundation, regex routing, stockage 3
     jours. Voir [Mailgun inbound routing](https://www.mailgun.com/features/inbound-email-routing/).
   - **IMAP polling** : possible mais déconseillé (latence, fiabilité, complexité
     OAuth Gmail/Microsoft).

2. **Adresse dédiée par org** :
   - Format simple : `support+{org_slug}@inbound.showdesk.io` ou
     `{org_slug}@inbound.showdesk.io` (sous-domaine MX dédié).
   - Format premium : alias custom pointant vers Showdesk via MX (ex:
     `support@acme.com` -> MX vers Postmark -> webhook Showdesk).
     Nécessite une étape de vérification DNS côté client (TXT/MX).

3. **Threading par en-têtes RFC 2822** :
   - Chaque email sortant Showdesk doit porter un `Message-ID` unique stable et
     récupérable, par ex `<ticket-{ref}.{message_uuid}@showdesk.io>`.
   - Toute réponse entrante : on lit `In-Reply-To` et `References`, on retrouve le
     ticket via le `Message-ID` qu'on a stocké.
   - **Fallback** : extraire la référence ticket dans le sujet (ex `[#SD-123]`)
     ou dans le `Reply-To` (ex `reply+{token}@inbound.showdesk.io`). Le token
     dans le `Reply-To` est la **méthode la plus robuste** car insensible aux
     clients mail qui mangent les en-têtes -- c'est ce que fait Zendesk, Front,
     etc.
   - Voir [Postmark threading](https://postmarkapp.com/support/article/1276-threading-unthreading-messages),
     [Zendesk threading](https://support.zendesk.com/hc/en-us/articles/4408821051034),
     [MailerSend ticketing thread](https://www.mailersend.com/blog/email-threading).

4. **Anti-spam et nettoyage** :
   - Vérifier SPF/DKIM/DMARC du sender entrant.
   - Strip de la signature et du quote `> On ... wrote:` (libs : `talon` Python
     côté Mailgun, ou parsing custom).
   - Liste de blocage (no-reply@, mailer-daemon@, abuse@, autoresponders).
   - Détection bounces (`X-Failed-Recipients`, status codes SMTP).

5. **Pièces jointes** : stockage S3 comme pour les attachments existants. Limites
   provider : Postmark 35 MB total, SES 40 MB, Mailgun 25 MB. Filtrer .exe/.bat
   comme on le fait déjà pour les uploads widget.

6. **DKIM/SPF côté Showdesk** : pour que les emails sortants ne tombent pas en
   spam, Showdesk doit signer avec DKIM (le provider transactional gère). Si on
   propose les alias custom (`support@acme.com`), il faut un DKIM signé pour le
   domaine du client -- c'est exactement ce que fait Postmark/SendGrid via leur
   Sender Domain.

### 1.3 Coût indicatif

- Pour un Showdesk early : Postmark Basic $15/mois pour le sortant, **upgrade à
  Pro $16,50/mois** dès qu'on veut l'inbound, jusqu'à 10 000 emails/mois inclus
  pour les deux flux. Largement suffisant pour les premiers clients.
- À l'échelle (>50 K emails/mois), basculer sur SES devient attractif : ~$5 pour
  50 K outbound + ~$5 pour 50 K inbound, mais effort de dev x3.

### 1.4 Complexité

- **2-3 sprints** pour une V1 décente : modèle `Channel`, parsing, threading,
  retry sur webhook, dashboard agent qui montre le canal email, signature inline
  préservée, fallback `Reply-To` token.
- Le piège classique : les **emails forwardés** par les endusers (le requester
  forward un email reçu d'ailleurs vers le support) cassent le threading ; il
  faut détecter `Fwd:` / `Tr:` et ouvrir un ticket distinct.

---

## 2. WhatsApp Business -- gros impact perçu

### 2.1 Pré-requis business côté client

- **Meta Business Manager** vérifié.
- **Numéro de téléphone dédié** (jamais utilisé sur WhatsApp grand public, sinon
  il faut le "déconnecter" d'abord). Peut être un numéro fixe vérifiable par
  appel/SMS.
- **Display name** approuvé par Meta (peut prendre 1-3 jours).
- Templates approuvés Meta pour les messages **en dehors** de la fenêtre de 24h.

C'est le canal avec **le plus de friction d'onboarding** -- ne pas sous-estimer
l'effort de support qu'on devra fournir aux clients qui veulent l'activer.

### 2.2 Modèle de tarification (depuis 1er juillet 2025)

Source : [Meta WhatsApp pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing).

- Avant juillet 2025 : facturation par **conversation** (24h) catégorisée
  (service / utility / authentication / marketing).
- Depuis juillet 2025 : facturation **par message délivré** (PMP -- Per-Message
  Pricing). Marketing reste cher, utility/auth bas, **service gratuit**.
- **Customer Service Window (CSW)** de 24h : quand l'enduser écrit, on peut
  répondre librement (texte, médias, templates) gratuitement pendant 24h. Chaque
  nouveau message du client réinitialise la fenêtre.
- **1 000 conversations service offertes / mois** par WABA. Au-delà : ~$0,005-0,02
  par message selon pays.
- **Free Entry Points** (clic depuis pub Click-to-WhatsApp ou bouton WhatsApp sur
  Facebook) : 72h gratuites au lieu de 24h.

Sources :
[WhatsApp Cloud Setup & Cost Guide 2026](https://chatarmin.com/en/blog/whatsapp-cloudapi),
[Pricing update July 1 2025](https://www.ycloud.com/blog/whatsapp-api-pricing-update),
[Customer service window guide](https://help.activecampaign.com/hc/en-us/articles/20679458055964-Understanding-the-24-hour-conversation-window-in-WhatsApp-messaging).

**Implication clé pour Showdesk** : pour un usage support pur (l'enduser écrit
en premier, l'agent répond dans 24h), **le coût marginal est quasi nul**. Le coût
n'apparaît que si on veut envoyer des messages **proactifs** hors fenêtre
(templates utility ou marketing).

### 2.3 Cloud API directe vs BSP

| Option | Avantages | Inconvénients |
|---|---|---|
| **Cloud API Meta directe** | Gratuit (juste les messages), SDK officiel, doc Meta | Setup complexe (Business Manager, vérification, templates), pas de support humain |
| **Twilio WhatsApp** | Onboarding plus simple, support Twilio, API multi-canal cohérente avec SMS/voice | +$0,005/msg de markup |
| **360dialog** | Markup zéro sur Meta, license $49-99/mois flat | Subscription fixe peu intéressante en early stage |
| **MessageBird (Bird)** | Plateforme multi-canal | +$0,005/msg + variable selon zone |

Recommandation pour Showdesk : **partir sur Twilio** pour la V1 (intégration plus
rapide, on garde Twilio pour SMS plus tard) puis **migrer sur Cloud API directe**
quand le volume justifie l'effort. Voir
[Twilio WhatsApp pricing](https://www.twilio.com/en-us/whatsapp/pricing),
[Twilio vs 360dialog](https://www.kommunicate.io/blog/twilio-vs-360dialog-a-comparison/).

### 2.4 Webhooks et flow technique

1. Webhook entrant Meta/Twilio sur `/api/v1/channels/whatsapp/webhook/`.
2. Vérification signature HMAC.
3. Match du numéro WhatsApp -> `EndUserIdentity` -> ticket existant ou nouveau.
4. Stockage du média (images/audio/vidéo) dans S3 -- WhatsApp expose une URL
   temporaire (15 min), il faut downloader vite.
5. Message créé dans la conversation, broadcast WebSocket aux agents comme un
   message widget.

### 2.5 Risques

- **RGPD** : il faut un **opt-in explicite et tracé** avant d'envoyer le moindre
  template. Ce que Showdesk doit fournir au client : un mécanisme pour collecter
  cet opt-in (case à cocher dans le widget, formulaire, etc.) et stocker la trace
  (date, source, IP). Voir [GDPR + WhatsApp](https://gettalkative.com/info/whatsapp-gdpr).
- **Numéro lié à l'org** : si le client ne paie plus, comment on lui rend son
  numéro vérifié ? Process à documenter dès le départ.

---

## 3. Instagram DM & Facebook Messenger

### 3.1 Pré-requis business

- Instagram : compte **Business** ou **Creator**, lié à une **page Facebook**, qui
  appartient à un Business Manager.
- Messenger : page Facebook + Business Manager.

Beaucoup de clients SaaS B2B n'ont pas ce setup -- c'est davantage un canal pour
les e-commerce / D2C / créateurs.

### 3.2 Tech

- **Graph API Meta** -- même infrastructure que WhatsApp Cloud, mêmes webhooks
  pour les nouveaux messages, mêmes notions de **fenêtre 24h**.
- Spécificités Instagram : `HUMAN_AGENT` tag permet de répondre jusqu'à **7 jours
  après** le dernier message client (très utile pour le support en effectif réduit).
- Voir [Instagram messaging webhooks](https://developers.facebook.com/docs/messenger-platform/instagram/features/webhook/),
  [Instagram messaging API](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/).

### 3.3 Verdict

À ajouter **après** WhatsApp (mêmes outils, mêmes webhooks Meta) mais hors
priorité tant qu'on cible les startups SaaS B2B. Pour la cible
**E-commerce / D2C** (cf. memory : "EC market = separate product/brand later"),
ça redevient **P0**.

---

## 4. Slack -- canal B2B SaaS naturel

Cf. [Phase 3 / Notification System](../../../ROADMAP.md) où Slack est déjà listé
comme intégration de **notification sortante**. Ici on parle de quelque chose
de plus ambitieux : Slack Connect comme **canal de conversation** entrant.

### 4.1 Cas d'usage

Beaucoup de startups SaaS B2B ouvrent un **canal Slack Connect partagé** avec leurs
gros clients. Aujourd'hui, ces conversations vivent en silo : les ingés répondent
dans Slack, rien n'est tracké, rien n'est compté dans les SLA, l'historique se
perd quand quelqu'un quitte. Outils existants (Plain, Pylon, Thena, ClearFeed)
montrent qu'il y a un vrai marché -- voir
[Slack customer support 2026](https://www.plain.com/blog/scale-slack-customer-support-2026),
[Top Slack integrations](https://www.usepylon.com/blog/slack-integrations-customer-support-2025).

### 4.2 Modèle conversationnel

- Un **canal Slack Connect = un client** (par convention `#support-{client}`).
- Chaque **thread** dans ce canal = une conversation (= un ticket Showdesk).
- Les agents répondent **depuis Slack** (le bot Showdesk poste), tout en gardant
  l'historique dans Showdesk (SLA, métriques, recherche).
- Reactions emoji = signaux : `:eyes:` triagé, `:white_check_mark:` résolu...

### 4.3 Tech

- App Slack (OAuth) avec scopes `channels:history`, `chat:write`,
  `reactions:read`, `users:read`.
- Events API webhook : `message.channels`, `message.im`.
- Mapping `slack_team_id + slack_channel_id` -> `Organization`.
- Mapping `slack_user_id` -> `EndUserIdentity` (resolve via email Slack quand
  possible).

Effort : **1 sprint pour notifications outbound** (déjà roadmappé), **3-4
sprints** pour une vraie ingestion bi-directionnelle.

---

## 5. Canaux secondaires

### 5.1 SMS (Twilio / Vonage)

- **Outbound notifications uniquement** dans un premier temps : "ticket résolu",
  "agent vous a répondu, ouvrez l'app" -- déjà listé dans
  [Notification System](../../../ROADMAP.md#notification-system).
- Tarifs : Twilio US $0,0083/SMS, FR ~$0,07/SMS, MMS $0,022. Numéro de $1,15/mois
  (US long code) à $15/mois (toll-free). Voir
  [Twilio SMS pricing](https://www.twilio.com/en-us/sms/pricing/us).
- **Two-way SMS** comme canal support : possible mais peu adapté aux startups SaaS
  (manque de richesse média), à réserver à des verticales spécifiques (immo,
  artisans, terrain).
- **Opt-in obligatoire** RGPD + lois locales (TCPA US, CNIL FR). Ne **pas** se
  lancer sans avoir bien le formulaire de consentement.

### 5.2 Microsoft Teams

- **Incoming webhooks** : sortant uniquement (pour les notifs agents). Microsoft
  les remplace progressivement par les **Workflows / Power Automate**.
- App Teams complète (canal de support inbound) : effort très significatif (App
  Studio, manifest, validation, distribution Teams Store).
- Voir [Microsoft Teams webhooks](https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook).
- **Verdict** : sortant only en P3, app complète seulement si demande explicite
  enterprise.

### 5.3 Discord

- API bot solide, slash commands, threads.
- Cible : startups avec **communauté Discord** (gaming, web3, dev tools). Pas la
  cible principale Showdesk (startups SaaS B2B).
- Effort modéré -- bot + commandes `/ticket` et webhook entrant sur les threads
  d'un canal `#support`.

### 5.4 Téléphone

Hors scope ici (renvoyé sur le sujet phone-support dédié).

---

## 6. Architecture conversationnelle unifiée

### 6.1 Comment les concurrents modélisent

- **Intercom** : tout est **conversation**. Pas de "ticket" distinct dans le
  modèle de base ; le ticket est une vue / un état d'une conversation. Le
  canal d'origine (chat widget, email, WhatsApp...) est un attribut.
- **Front** : modèle **Inbox -> Channel -> Conversation -> Message**. Un Channel
  est typé (email address, SMS number, FB page, IG handle, Slack team...) et
  attaché à une Inbox. Un Contact a plusieurs **handles** (email, phone,
  facebook_id...) qu'on matche via une logique de fusion. Voir
  [Front channels](https://help.front.com/en/articles/2076).
- **Zendesk** : "ticket" reste l'unité, avec un champ `channel`. L'identité
  enduser est consolidée via un User unique avec multiples `identities` (email,
  twitter, phone...).
- **Chatwoot** (open-source, intéressant pour copier le modèle) :
  `Inbox` polymorphique, `Channel` (Email / API / FacebookPage / WhatsApp / Sms /
  Telegram / Line...), `Contact` avec `ContactInbox` qui lie un contact à un
  inbox via la clé spécifique au canal (PSID, phone, email...). Voir
  [Chatwoot channel architecture](https://deepwiki.com/chatwoot/chatwoot/7.1-email-configuration).
- **Crisp** : annoncé comme "channel-agnostic by design", chat widget + WhatsApp +
  Insta + Messenger + SMS + email tous routés vers le même Inbox. Voir
  [Crisp omnichannel](https://crisp.chat/en/blog/best-multichannel-ai-support-platform/).

### 6.2 Modèle de données suggéré pour Showdesk

Sans rentrer dans le code -- juste les concepts.

```
Organization
  └── ChannelConfig (1..N)        # config d'un canal pour cette org
       - kind                       # widget | email | whatsapp | slack | ig | fb | sms | discord | teams
       - status                     # active | paused | failed
       - credentials                # JSON par-canal (token, webhook secret, channel_id...)
       - inbox_id / address         # adresse email entrante, numéro WhatsApp, slack team_id...
       - settings                   # signature, auto-reply, routing rules

Conversation                       # (= ce qu'on appelle "ticket" aujourd'hui)
  - org
  - reference (SD-xxxx)
  - subject
  - status, priority, assignee, team, tags, ...
  - primary_channel_kind            # le canal d'origine (utile pour stats)
  - external_user_identity_id      # pointer unique vers l'enduser

Message
  - conversation
  - channel                         # canal sur lequel CE message est arrivé/parti
  - direction                       # inbound | outbound
  - external_id                     # message_id email, wamid WhatsApp, slack ts, ig mid...
  - in_reply_to_external_id        # pour threading futur (email surtout)
  - body_html, body_text
  - attachments (=> S3)
  - delivery_status                 # sent | delivered | read | failed
  - sender_kind                     # enduser | agent | system | bot
  - sender_user / sender_identity
  - sent_at, delivered_at, read_at
  - is_internal_note (bool)

EndUserIdentity                    # le "Contact" unifié
  - org
  - display_name
  - merged_into                    # pour la fusion soft

EndUserHandle                      # 1..N handles par identité
  - identity
  - kind                           # email | phone | whatsapp | slack | facebook | instagram | external_id
  - value                          # normalisé (E.164 pour phone, lowercase pour email)
  - verified (bool)
  - first_seen_at, last_seen_at
```

**Logique de matching** (à appliquer à chaque message entrant) :

1. Normaliser le handle (E.164, lowercase email, etc.).
2. Chercher un `EndUserHandle` existant dans l'org -> récupérer l'`EndUserIdentity`.
3. Si non trouvé : créer une nouvelle `EndUserIdentity` + `EndUserHandle`.
4. Quand un agent fusionne deux identités : marquer `merged_into`, déplacer toutes
   les `Conversation` et `EndUserHandle`. Soft-merge réversible.

**Logique de bind conversation**:

- Email avec `In-Reply-To` connu -> append au ticket existant.
- Email sans header mais avec token dans `Reply-To` -> append au ticket.
- WhatsApp/SMS d'un numéro connu, dernière conversation < 7 jours -> append.
- Sinon -> nouvelle conversation, bind à l'identité.

### 6.3 Migration depuis l'existant

Showdesk a aujourd'hui `Ticket` + `TicketMessage`. La migration peut être douce :

1. Renommer **conceptuellement** `Ticket` -> `Conversation` côté API/UI plus tard,
   sans toucher la table tout de suite (on garde `Ticket` en base, on ajoute juste
   les nouveaux champs).
2. Ajouter `Message.channel_kind` (default `widget`) et `Message.external_id` ->
   suffit déjà pour identifier la source d'un message.
3. Ajouter `EndUserIdentity` séparé du `external_user_id` actuel (qui est
   simplement un string). Migration : créer une identity par `external_user_id`
   distinct.
4. Sortir le canal email en MVP avant de toucher la sémantique du ticket.

---

## 7. Recommandations de priorisation

### Phase A (next, ~1-2 mois)

1. **Email entrant via Postmark Inbound** -- adresse `support+{org_slug}@inbound.showdesk.io`,
   threading par `Message-ID` + token `Reply-To`.
2. **Email sortant enrichi** -- ajouter `Message-ID` stable, headers In-Reply-To,
   `Reply-To` token, signature org-personnalisée (qui est déjà partiellement dans
   la roadmap "Email Design & Branding").
3. **Modèle `EndUserIdentity` minimal** -- juste pour permettre à plusieurs emails
   du même utilisateur de pointer vers la même fiche. Évite de devoir refactor
   plus tard.

### Phase B (~2-3 mois après A)

4. **Slack Connect** comme canal entrant -- vise les startups SaaS B2B qui ont
   déjà un canal Slack avec leurs clients. Big differentiator vs Zendesk/Freshdesk
   qui ne le font pas bien.
5. **WhatsApp Business via Twilio** -- onboarding plus rapide, on évite la galère
   Meta direct au début, on monétise vite.

### Phase C (~6 mois)

6. **Migration WhatsApp Twilio -> Cloud API directe** quand volume > ~10 K
   conv/mois.
7. **Instagram DM + Messenger** (mêmes webhooks Meta, peu d'effort
   incremental) -- surtout si on attaque la verticale e-commerce.
8. **SMS outbound notifications** (Twilio) pour l'urgence / on-call.

### Phase D / opportuniste

9. Microsoft Teams (uniquement sur demande client enterprise).
10. Discord (si segment "communauté" devient prioritaire).
11. SMS two-way (verticales spécifiques).

---

## 8. Risques et points d'attention

### 8.1 RGPD / privacy

- **Opt-in explicite** pour tout canal autre que celui où l'enduser nous a
  contacté en premier. Si l'enduser écrit par email, on peut répondre par email.
  On **ne peut pas** lui envoyer un WhatsApp sans consentement séparé.
- **Conservation des messages** : aligner sur la politique générale Showdesk
  (aujourd'hui `expires_at` sur les vidéos). Les messages WhatsApp ont une
  contrainte forte : Meta retient les médias 14 jours, après il faut les
  ré-uploader. À gérer côté backend.
- **DPA (Data Processing Agreement)** : chaque BSP / provider exige un DPA
  signé. Twilio, Postmark, Mailgun en ont des standardisés. Meta : DPA via le
  Business Manager.
- **Localisation des données** : SES/Postmark proposent des régions UE.
  Mailgun a une région UE explicite (mailgun.eu). À privilégier pour les
  clients européens.

### 8.2 Anti-abuse

- Adresses inbound publiques = cibles de spam massive. Prévoir :
  - Rate limit par IP envoyeuse / par domaine.
  - Filtrage SPF/DKIM/DMARC dur (les domaines qui n'authentifient pas vont en
    quarantaine).
  - Pas de création d'org / d'enduser via email entrant (l'org doit déjà avoir
    été configurée).

### 8.3 Coût caché

- Les **médias entrants** WhatsApp/IG (vidéos surtout) explosent le storage S3
  -- prévoir une politique d'expiration ou compression côté ingestion.
- Les emails entrants avec **gros attachments** (PDF de 30 MB, Word de 20 MB) :
  même problème.
- Les **bounces et auto-replies** mal filtrés peuvent créer des centaines de
  faux tickets par jour. Avoir un dashboard "messages rejetés" dès la V1.

### 8.4 Ergonomie agent

- Les agents doivent **savoir d'où vient un message** sans cliquer (icône
  canal devant chaque message).
- L'agent doit pouvoir **changer de canal** au cours d'une conversation : un
  ticket démarré par email peut continuer en widget si l'enduser revient sur le
  site (à condition qu'on l'ait identifié des deux côtés).
- **Indicateur de fenêtre 24h WhatsApp/IG** : afficher en clair dans l'UI
  agent "Vous ne pouvez répondre librement que pendant Xh, après il faudra un
  template" -- sinon les agents vont être surpris.

### 8.5 Onboarding client

- Email custom (`support@acme.com`) : process DNS à expliquer, sinon les clients
  abandonnent. Préparer une doc + un assistant intégré qui vérifie les MX.
- WhatsApp : process Meta long et capricieux. Soit on le **fait à la main pour
  le client** (concierge onboarding) soit on intègre un BSP qui le simplifie
  (Twilio le fait moyennement, 360dialog mieux).
- Slack Connect : c'est le **client final** (l'admin du workspace Slack du
  client de notre client) qui doit accepter l'invitation. Friction non-Showdesk
  mais à anticiper dans le flow.

---

## 9. Sources

- [Postmark Inbound Webhook](https://postmarkapp.com/developer/webhooks/inbound-webhook)
- [Postmark Pricing](https://postmarkapp.com/pricing)
- [Postmark threading](https://postmarkapp.com/support/article/1276-threading-unthreading-messages)
- [AWS SES Pricing](https://aws.amazon.com/ses/pricing/)
- [Mailgun Inbound Routing](https://www.mailgun.com/features/inbound-email-routing/)
- [MailerSend ticket threading guide](https://www.mailersend.com/blog/email-threading)
- [Zendesk email threading](https://support.zendesk.com/hc/en-us/articles/4408821051034)
- [WhatsApp Cloud API pricing (Meta)](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)
- [WhatsApp Business platform pricing](https://business.whatsapp.com/products/platform-pricing)
- [WhatsApp pricing update July 1 2025](https://www.ycloud.com/blog/whatsapp-api-pricing-update)
- [WhatsApp 24h customer service window](https://help.activecampaign.com/hc/en-us/articles/20679458055964-Understanding-the-24-hour-conversation-window-in-WhatsApp-messaging)
- [Twilio WhatsApp pricing](https://www.twilio.com/en-us/whatsapp/pricing)
- [Twilio vs 360dialog](https://www.kommunicate.io/blog/twilio-vs-360dialog-a-comparison/)
- [WhatsApp GDPR compliance](https://gettalkative.com/info/whatsapp-gdpr)
- [Instagram messaging webhook (Meta)](https://developers.facebook.com/docs/messenger-platform/instagram/features/webhook/)
- [Instagram messaging API](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/)
- [Twilio SMS pricing US](https://www.twilio.com/en-us/sms/pricing/us)
- [Microsoft Teams Incoming Webhooks](https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook)
- [Slack customer support best practices 2026 (Plain)](https://www.plain.com/blog/scale-slack-customer-support-2026)
- [Slack support integrations 2025 (Pylon)](https://www.usepylon.com/blog/slack-integrations-customer-support-2025)
- [Front channel/inbox architecture](https://help.front.com/en/articles/2076)
- [Chatwoot channel architecture (DeepWiki)](https://deepwiki.com/chatwoot/chatwoot/7.1-email-configuration)
- [Crisp omnichannel](https://crisp.chat/en/blog/best-multichannel-ai-support-platform/)

---

*Document de brainstorm -- mis à jour 2026-05-01.*
