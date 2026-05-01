# Gestion des Contacts et Companies — Brainstorm

> Document de synthèse — 2026-05-01
>
> Sujet : modélisation et UX d'un CRM-light intégré au helpdesk Showdesk pour
> que ses Organizations clientes puissent gérer leurs propres endusers
> (contacts) et les entreprises auxquelles ils appartiennent (companies).

---

## TL;DR

- **Showdesk vise les startups SaaS B2B**. Pour ce public, la "fiche client" ne
  peut pas se limiter à un email + nom : il faut au minimum une notion de
  **Company** (l'entreprise cliente de l'Organization), une **timeline 360°**
  agrégeant tickets + événements widget, et des **custom attributes** typés.
- **Aujourd'hui dans Showdesk** il n'existe pas de modèle Contact ni Company
  dédié. Les endusers du widget vivent dans `WidgetSession` (ID localStorage,
  email/name optionnels, `external_user_id` HMAC) et accessoirement dans
  `User.role = end_user` quand ils ont un compte. C'est suffisant pour ouvrir
  un ticket, pas pour faire du support B2B sérieux.
- **Naming proposé** : on garde `Organization` côté Showdesk (le tenant), on
  introduit **`Contact`** (le enduser, remplace progressivement
  `User.role=end_user` côté UI) et **`Company`** (l'entreprise du contact).
  Le terme "Account" est trop ambigu (souvent confondu avec compte
  d'authentification), "Organization" est déjà pris.
- **Modèle de données minimum viable** : `Contact` (email canonique,
  `external_id`, name, avatar, lifecycle stage, custom attributes JSONB,
  belongs_to Company), `Company` (name, domain, plan, MRR, custom attributes
  JSONB), `CustomAttribute` (définition par Organization : key, label, type,
  options). Reprendre la convention Intercom/Front : 50 attributs max par
  entité, types `string|number|date|bool|enum|list`.
- **Identification** : conserver le mécanisme HMAC actuel pour le widget,
  l'étendre côté API pour ingérer des attributs au moment de l'identify
  (style Intercom `Intercom('boot', { user_id, email, custom_data })`).
  Auto-link au domaine email pour la Company, surchargeable manuellement.
- **Enrichissement auto** : Clearbit est mort (acquis par HubSpot puis
  sunsettés en 2025). Pour Showdesk, **on skippe au MVP** et on prévoit un
  hook de provider plus tard (Apollo, People Data Labs, ou simple lookup
  logo via `https://logo.dev` / `clearbit/logo` mirror).
- **Vue 360°** : page Contact = profil + custom attrs + timeline tickets +
  events widget + notes internes. Page Company = profil + liste contacts +
  liste tickets agrégée + custom attrs.
- **Segmentation** : reporter au-delà du MVP. Au MVP = filtres simples sur
  list + recherche full-text email/name/company.
- **Import / sync** : MVP = CSV import + endpoint API public. Sync CRM externe
  (HubSpot, Attio) en Phase 4 via webhooks ou intégrations dédiées.
- **RGPD** : Showdesk est sous-traitant. Chaque Organization "possède" ses
  contacts. Nécessite un endpoint export (Article 15) + endpoint suppression
  / anonymisation (Article 17) par contact, accessible aux admins de
  l'Organization. La suppression doit cascader vers messages mais pas
  vers tickets : on **anonymise** plutôt que de supprimer pour préserver la
  cohérence du thread (cf. EDPB 2025).

---

## 1. Vocabulaire — proposition définitive

| Terme | Définition Showdesk | Équivalent Intercom | Équivalent Zendesk | Équivalent HelpScout | Équivalent Front |
|-------|---------------------|---------------------|--------------------|----------------------|------------------|
| **Organization** | Le tenant Showdesk (Acme SaaS qui paie Showdesk pour son support). Existe déjà (`apps.organizations.Organization`). | "Workspace" | "Account" / "Subdomain" | "Account" | "Workspace" |
| **Contact** *(nouveau)* | Le enduser : la personne qui ouvre un ticket auprès de l'Organization. Remplace progressivement `User.role=end_user` dans l'UI agent. | "User" / "Contact" / "Lead" | "End user" / "User" | "Customer" | "Contact" |
| **Company** *(nouveau)* | L'entreprise à laquelle appartient le Contact (Startup Inc, cliente d'Acme). | "Company" | "Organization" (terme malheureux) | "Company" | "Account" |
| **Agent** / **User** | L'employé de l'Organization qui traite les tickets. Existe déjà (`User.role=agent\|admin`). | "Teammate" / "Admin" | "Agent" | "User" | "Teammate" |

### Pourquoi ce naming

- **Garder `Organization`** : déjà partout dans le code, modifier coûterait
  cher. C'est aussi le terme historique (Phase 0 ROADMAP).
- **`Contact` et non `Customer`** : "Customer" suggère une relation
  commerciale active (paye, abonné). Un visiteur anonyme qui ouvre un
  ticket n'est pas encore "customer". Intercom et Front ont fait le même
  choix.
- **`Company` et non `Account`** : "Account" en français/anglais évoque
  immédiatement un compte d'auth, et collide avec `Organization` chez
  Zendesk (qui appelle ses Companies "Organizations", source de
  confusion permanente pour leurs clients). HelpScout, Intercom, et
  Pylon utilisent tous "Company".
- **Schéma mental** : `Organization (1) -> (N) Company -> (N) Contact -> (N) Ticket`.

### Migration depuis le modèle actuel

`User.role=end_user` est aujourd'hui peu utilisé. La majorité des endusers
arrivent comme `WidgetSession` anonymes ou identifiés par HMAC. Plan :

1. Créer le modèle `Contact` séparé de `User` (conserver `User` pour
   agents/admins seulement à terme).
2. Au moment d'un `WidgetSession.email` non vide ou `external_user_id`
   défini, créer / matcher un `Contact`.
3. Migrer les `User.role=end_user` existants vers `Contact` (script de
   data migration). Garder une FK back-pointer le temps de la transition.

---

## 2. Comparatif des concurrents

### Intercom — référence du domaine

- Trois objets : **Lead** (anonyme), **Contact** (= "User", identifié,
  payant), **Company**. Tout objet a un `id` Intercom + un `external_id`
  (= `user_id` côté client) + un `email`.
- Custom Data Attributes (CDA) : créables côté UI ou via API
  `/data_attributes`. Types : `string`, `integer`, `float`, `boolean`,
  `date`, `enum` (liste fermée). On ne peut pas créer une CDA portant le
  nom d'un attribut standard. Limite *historique* ~250 par workspace.
- Identité sécurisée : HMAC-SHA256 du `user_id` (ou email) avec un secret
  workspace, exactement le même schéma que Showdesk fait déjà sur
  `Organization.widget_secret`. Intercom recommande JWT comme évolution
  mais maintient HMAC pour rétrocompat.
- Companies : un Contact peut appartenir à **plusieurs** Companies, avec
  rôle implicite via custom attribute. Le rattachement se fait au moment
  de l'identify : `Intercom('update', { company: { id, name, plan, ... } })`.
- Segments : règles dynamiques (`plan == "pro" AND last_seen > 7d`),
  utilisables pour broadcasts, automation, reporting.
- **Force** : modèle data riche, APIs cohérentes, identify côté JS très
  bien pensé.
- **Faiblesse** : devient cher dès qu'on dépasse quelques milliers de
  contacts, courbe d'apprentissage, beaucoup de fonctionnalités hors
  support pur (marketing, CDP).

### Zendesk — référence enterprise

- Objets : **User** (toute personne — end-user OU agent), **Organization**
  (= la Company chez nous, naming malheureux), **Ticket**.
- Un User peut appartenir à plusieurs Organizations. Les Tickets peuvent
  être assignés à une Organization (= attribut), ce qui permet le routing
  par compte.
- Custom fields séparés : User fields, Organization fields, Ticket fields.
  Types : text, multi-line, dropdown, multi-select, numeric, decimal, date,
  checkbox, regex. Visibles agent uniquement (end-users ne voient pas les
  org fields).
- Custom Objects (depuis 2023) : créer des entités arbitraires liées aux
  standards via lookup fields. Remplace progressivement les "custom user
  fields".
- **Force** : matrice de droits très fine, custom objects, intégration
  reporting (Explore).
- **Faiblesse** : verbiage confus (Organization = Company), UX datée,
  surdimensionné pour startups.

### HelpScout — référence simplicité

- Objets : **Customer** (= Contact), **Company**.
- "Properties" remplacent les custom fields : 50 par entité (Customer + Company),
  types text/number/dropdown. Slugs alphanumériques, kebab-case, uniques par
  workspace.
- Beacon JavaScript API : `Beacon('identify', { name, email, signature, ... })`
  où `signature` est le HMAC.
- Pas de notion de Lead — tout le monde est Customer.
- **Force** : simplicité, ergonomie, limite à 50 properties qui force le
  focus.
- **Faiblesse** : pas de segmentation avancée, pas de Custom Objects,
  pas multi-Company par Customer.

### Front — référence multi-canaux

- Objets : **Contact**, **Account** (= la Company chez nous).
- 50 custom fields max par catégorie (Contacts, Accounts, Teammates,
  Inboxes, Conversations).
- Custom fields utilisables dans rules, message templates, signatures,
  CRM sync mapping.
- Account custom fields : Revenue, Account Manager, Account Tier — exactement
  le use-case B2B SaaS.
- **Force** : multi-channels (email, SMS, Slack, WhatsApp, voice) tous
  rattachés au même Contact, sync CRM bidirectionnel mature.
- **Faiblesse** : positionné inbox plutôt que helpdesk, custom fields peu
  typés (souvent juste string).

### Plain — référence developer-first

- API-first, programmable comme Stripe/Twilio. "Customers" et "Tiers"
  (= Companies). Custom timeline events arbitraires.
- Modèle data exposé via GraphQL, avec un focus fort sur les custom
  attributes typés.
- **Force** : extrêmement extensible, parfait pour SaaS techniques.
- **Faiblesse** : très orienté ingénieur, UX de gestion de masse encore en
  construction.

### Pylon — référence B2B / Slack-first

- "Customers" (Contact) + "Accounts" (Company) avec sync CRM
  Salesforce/HubSpot natif. Ingère "Health Scores" externes
  (Gainsight, etc.).
- Identifie un Contact à travers Slack Connect, email, web — un seul
  profil unifié multi-channel.
- **Force** : pensé B2B SaaS dès le début, multi-stakeholder par Account
  (un même client a 5 personnes qui pingent le support).
- **Faiblesse** : pas de gestion fine des contacts anonymes (Slack force
  l'identité), nouveau, écosystème intégrations limité.

### Synthèse des points-clés

- **Tous** distinguent Contact/User et Company/Account (sauf HelpScout qui
  utilise "Customer" pour le Contact). Intercom et Front sont les naming
  les plus clairs.
- **Tous** plafonnent les custom attributes à ~50 par entité (sauf Intercom
  ~250). Force le client à se discipliner — c'est sain.
- **Tous** acceptent le multi-Company par Contact, mais c'est rarement
  utilisé en pratique. **Pour Showdesk MVP : 1 Company par Contact**,
  on relâchera plus tard si besoin.
- **Tous** font du HMAC pour l'identité widget. Showdesk est déjà aligné.

---

## 3. Modèle de données recommandé

### Vue d'ensemble

```
Organization (existant)
  └─ Company (1:N)            # créées par l'Organization
       └─ Contact (1:N)       # appartiennent à 0 ou 1 Company
            ├─ Ticket (1:N)   # FK déjà existante (Ticket.requester)
            ├─ WidgetSession (1:N)   # rattachement post-identify
            └─ ContactNote (1:N)     # notes internes agents

  └─ ContactAttributeDef (1:N)  # définitions des custom attrs
  └─ CompanyAttributeDef (1:N)  # idem côté Company
```

### Modèle `Contact`

Champs core (alignés sur Intercom + Front) :

```python
class Contact(TimestampedModel):
    organization = FK(Organization, related_name="contacts")  # tenant
    company = FK(Company, null=True, blank=True, related_name="contacts")

    # Identifiants — au moins un des trois doit être présent
    email = EmailField(blank=True, db_index=True)
    external_id = CharField(max_length=255, blank=True, db_index=True)
    phone = CharField(max_length=30, blank=True)

    # Profil
    name = CharField(max_length=255, blank=True)
    avatar_url = URLField(blank=True)         # rempli par enrichment OU upload
    job_title = CharField(max_length=255, blank=True)
    locale = CharField(max_length=10, blank=True)
    timezone = CharField(max_length=50, blank=True)

    # Lifecycle (dérivé, pas saisi à la main)
    first_seen_at = DateTimeField(null=True)
    last_seen_at = DateTimeField(null=True)
    last_contacted_at = DateTimeField(null=True)  # dernier ticket / message
    is_unsubscribed = BooleanField(default=False)

    # Custom attributes — JSONField indexé GIN
    attributes = JSONField(default=dict, blank=True)
    # ex: {"plan": "pro", "mrr": 49, "signup_date": "2026-01-15"}

    class Meta:
        constraints = [
            # email unique par org (si renseigné)
            UniqueConstraint(
                fields=["organization", "email"],
                condition=Q(email__gt=""),
                name="unique_contact_email_per_org",
            ),
            UniqueConstraint(
                fields=["organization", "external_id"],
                condition=Q(external_id__gt=""),
                name="unique_contact_external_id_per_org",
            ),
        ]
        indexes = [
            Index(fields=["organization", "email"]),
            Index(fields=["organization", "external_id"]),
            Index(fields=["organization", "company"]),
        ]
```

Notes :

- `email` et `external_id` sont **optionnels mais uniques par org** (partial
  unique constraint). Permet à un anonyme de devenir un Contact sans
  email.
- `attributes` JSONField : flexibilité totale, mais validation côté
  serializer contre la table `ContactAttributeDef`. GIN index pour
  filtrage efficace.
- `last_seen_at` mis à jour par le widget (heartbeat session) ou par
  toute requête API authentifiée pour ce contact.

### Modèle `Company`

```python
class Company(TimestampedModel):
    organization = FK(Organization, related_name="companies")

    # Identifiants
    external_id = CharField(max_length=255, blank=True, db_index=True)
    name = CharField(max_length=255)
    domain = CharField(max_length=255, blank=True, db_index=True)
    # domain unique par org (si renseigné) -> sert au matching auto

    # Profil
    logo_url = URLField(blank=True)
    industry = CharField(max_length=100, blank=True)
    size = CharField(max_length=50, blank=True)  # "1-10", "11-50", ...
    website = URLField(blank=True)

    # Lifecycle / business
    plan = CharField(max_length=100, blank=True)
    mrr_cents = PositiveIntegerField(null=True, blank=True)
    health_score = PositiveSmallIntegerField(null=True, blank=True)  # 0-100
    signed_up_at = DateTimeField(null=True, blank=True)
    churned_at = DateTimeField(null=True, blank=True)

    attributes = JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["organization", "external_id"],
                condition=Q(external_id__gt=""),
                name="unique_company_external_id_per_org",
            ),
            UniqueConstraint(
                fields=["organization", "domain"],
                condition=Q(domain__gt=""),
                name="unique_company_domain_per_org",
            ),
        ]
```

Notes :

- `domain` unique par org : c'est ce qui permet de **matcher
  automatiquement un Contact à sa Company** quand on a son email
  (`alice@startup.com` -> Company `domain=startup.com`).
- `mrr_cents` en entier (pas de Decimal) : suffit pour les use-cases
  startups, simplifie le tooling.
- `health_score` : pour ingérer des scores externes (Gainsight style),
  optionnel.

### Modèles `ContactAttributeDef` / `CompanyAttributeDef`

Définition des custom attrs créés par chaque Organization :

```python
class CustomAttributeDef(TimestampedModel):
    """Base abstraite pour les custom attrs."""

    class Type(TextChoices):
        STRING = "string"
        NUMBER = "number"
        BOOLEAN = "boolean"
        DATE = "date"
        ENUM = "enum"        # liste fermée
        URL = "url"

    organization = FK(Organization)
    key = SlugField(max_length=64)        # snake_case, immuable
    label = CharField(max_length=120)     # affichable
    type = CharField(choices=Type.choices)
    description = TextField(blank=True)
    options = JSONField(default=list, blank=True)  # pour ENUM
    is_required = BooleanField(default=False)
    is_archived = BooleanField(default=False)
    position = PositiveIntegerField(default=0)

    class Meta:
        abstract = True
        unique_together = [("organization", "key")]


class ContactAttributeDef(CustomAttributeDef):
    pass


class CompanyAttributeDef(CustomAttributeDef):
    pass
```

Limite logicielle : **50 par entité par Organization** (cf. HelpScout/Front).

### Modèle `ContactNote`

```python
class ContactNote(TimestampedModel):
    contact = FK(Contact, related_name="notes")
    author = FK(User)         # agent qui a écrit la note
    body = TextField()
    # pas de privacy : interne par construction (pas de visibilité enduser)
```

Identique pour `CompanyNote` (à venir, faible priorité).

### Évolutions modèle `WidgetSession` (existant)

```python
# Ajouter
contact = FK(Contact, null=True, blank=True, related_name="sessions")
```

Logic :

- Au boot du widget avec HMAC valide -> on cherche/crée le Contact
  (`get_or_create` sur `(organization, external_id)` ou `(organization, email)`)
  et on lie la session.
- Si l'enduser fournit son email plus tard via le nudge contact, on fait
  un `get_or_create` sur l'email et on lie.

### Évolutions modèle `Ticket` (existant)

```python
# Ajouter
contact = FK(Contact, null=True, blank=True, related_name="tickets")
```

`requester` (FK User) reste pour rétrocompat ; à terme, `requester` ne
sert que pour les tickets ouverts par un agent et `contact` est la
référence canonique. Les deux peuvent co-exister pendant la transition.

---

## 4. UX recommandée

### Sidebar

Ajouter une entrée **"Contacts"** dans la sidebar agent, entre "Tickets"
et "Team". Sous-onglets en haut de page : `Contacts | Companies`.

### Page liste Contacts

- Colonnes par défaut : avatar, name, email, company.name, last_seen_at,
  open_tickets_count, plan (custom attr).
- Colonnes configurables par l'agent (à terme — pas MVP).
- Filtres en barre supérieure : recherche full-text (email/name),
  company, custom attrs (au minimum tous les `enum` et `bool`).
- Bouton "Add contact" (création manuelle) + "Import CSV".
- Pagination 25 / 50 / 100.

### Page détail Contact

Layout 3 colonnes (s'inspire d'Intercom et Front) :

- **Gauche (1/4)** : profil — avatar, name, email, phone, company avec
  logo cliquable, custom attributes éditables inline. "Edit contact"
  CTA. Boutons RGPD : "Export data" / "Delete contact".
- **Centre (1/2)** : timeline chronologique inversée — tickets
  (avec status), messages widget, événements (page vue, action
  produit — Phase 2), notes internes. Filtres : "All / Tickets only /
  Notes only". Bouton "Add note" en haut.
- **Droite (1/4)** : récap — nb tickets total / open / closed,
  first_seen, last_seen, MRR de la Company, lien "View company".

### Page liste Companies

- Colonnes : logo, name, domain, contacts_count, open_tickets_count,
  plan, mrr.
- Filtres : recherche, plan, custom attrs.
- "Add company" + "Import CSV".

### Page détail Company

Layout similaire mais pivoté autour des contacts :

- **Gauche** : profil Company — logo, name, domain, custom attrs (plan,
  MRR, health_score, etc.), website cliquable.
- **Centre** : 2 onglets — "Tickets" (tous les tickets de tous ses
  contacts, agrégés) / "Activity" (timeline globale).
- **Droite** : "People" — liste des contacts de la Company avec
  avatar + role + last_seen, bouton "Add contact".

### Sidebar latérale dans le ticket detail

Dans la page ticket, **remplacer la fiche enduser actuelle par un
résumé Contact + Company** :

- Nom + avatar + email + lien vers la fiche Contact.
- Si Company : logo + name + plan + lien vers la fiche Company.
- 3 derniers custom attrs marqués "show in sidebar" (cf. Intercom).
- "View all attributes" (drawer).

### UX d'identification depuis le widget

Pas de changement visuel majeur, mais en backend :

- Le widget envoie `external_id`, `email`, `name`, et optionnellement
  `company: { external_id, name, domain }`.
- Showdesk crée/match Contact + Company silencieusement.
- Le contact apparaît immédiatement dans la liste agent.

---

## 5. Stratégie d'identification

### Côté widget (existant + extension)

Schéma actuel :

```js
window.Showdesk.init({
  token: "xxx",
  user: { id: "user_123", email: "alice@startup.com", name: "Alice" },
  user_hash: "<hmac-sha256(user.id, widget_secret)>",
});
```

Extension proposée — accepter `traits` et `company` (style Intercom) :

```js
window.Showdesk.init({
  token: "xxx",
  user: {
    id: "user_123",
    email: "alice@startup.com",
    name: "Alice",
    traits: {
      plan: "pro",
      signup_date: "2026-01-15T00:00:00Z",
      role: "admin",
    },
  },
  user_hash: "<hmac>",
  company: {
    id: "company_42",
    name: "Startup Inc",
    domain: "startup.com",
    traits: { mrr: 4900, plan: "pro" },
  },
});
```

Backend : à la réception, sur `WidgetSession.boot`, faire :

1. `Contact.objects.update_or_create(organization=..., external_id="user_123", defaults={email, name, ...})`.
2. Si `company` fourni : `Company.objects.update_or_create(organization=..., external_id="company_42", defaults={...})` puis `contact.company = company`.
3. Si pas de `company` mais email contient un domaine non-public :
   tentative auto-link sur `Company.domain`.
4. Mettre à jour les `attributes` (JSONField) pour les traits validés
   contre `ContactAttributeDef` / `CompanyAttributeDef`.
5. `WidgetSession.contact = contact`.

### Côté API serveur (nouveau)

REST endpoint admin :

- `POST /api/v1/contacts/identify/` — upsert Contact (et Company),
  payload identique au widget (sans `user_hash` car authentifié JWT).
  Use-case : sync depuis le backend du client (Webhook Stripe, signup,
  etc.) plutôt que d'attendre le widget.
- `POST /api/v1/contacts/{id}/attributes/` — bulk upsert d'attrs.
- Endpoints CRUD classiques `GET/PATCH/DELETE /api/v1/contacts/{id}/`,
  idem `/companies/`.

### Anti-spam et validation

- Rate limit identify : 60/min/widget_token.
- Refuser silencieusement les `traits` qui n'existent pas en
  `ContactAttributeDef` ; les logger pour aider l'admin à créer la
  définition (style Intercom "schema-on-write" doux).
- `email` validé via Django EmailValidator + (optionnel) MX check
  asynchrone Celery.

### Merge de doublons

MVP : merge **manuel** uniquement, depuis la fiche Contact. UI = "Find
duplicates" qui propose Contacts du même org partageant email partiel
ou name. Validation par l'agent.

V2 : auto-merge silencieux quand un identify avec `external_id` arrive
sur un Contact qui n'avait que l'email (les deux fusionnent), à la
manière d'Intercom.

---

## 6. Enrichissement automatique — position

### Constat 2026

- **Clearbit est mort en tant que produit standalone** : acquis par
  HubSpot fin 2023, free tools sunsettés en avril 2025, Logo API
  arrêtée en décembre 2025. L'enrichissement Clearbit n'est plus dispo
  que via HubSpot.
- **Apollo** : enrichment + sales engagement, ~25 K USD/an pour le tier
  équipé d'API. Trop cher et trop "sales" pour être un choix par
  défaut.
- **People Data Labs (PDL)** : 1.5 Md+ records, API-first, idéal
  enrichissement à grande échelle. Pricing à la requête, raisonnable.
- **logo.dev / favicon-grabber** : alternatives gratuites pour le logo
  uniquement, à partir du domaine.

### Recommandation

**Skipper l'enrichissement automatique au MVP.** Raisons :

1. C'est cher, et la valeur perçue est faible quand le client a déjà
   ses données dans son SaaS et les pousse via identify.
2. Les mauvais matches (mauvais logo, mauvais secteur) coûtent plus
   cher en confiance qu'ils n'apportent en valeur.
3. La majorité de nos clients startups ont déjà la donnée fraîche dans
   leur backend — il est plus utile de leur faciliter l'identify (cf.
   §5) que de payer un tiers pour redécouvrir leurs propres clients.

**Compromis pragmatique pour le MVP** :

- **Logo Company auto-fetch** depuis le `domain` via `https://logo.dev`
  (gratuit, API simple, fallback favicon). Tâche Celery au moment où
  on crée une Company avec un domain.
- **Aucune autre donnée tirée d'un tiers**.

**Architecture pour plus tard** : interface `EnrichmentProvider` avec une
implem `LogoDevProvider` au MVP, et possibilité d'ajouter
`PeopleDataLabsProvider`, `ApolloProvider` derrière une feature flag
au niveau Organization. Le client peut configurer sa propre clé API
("bring your own key") ce qui transfère le coût.

---

## 7. Considérations RGPD

### Position de Showdesk

- **Showdesk = sous-traitant** au sens RGPD : il traite les données
  personnelles (Contact, Company) pour le compte de l'Organization,
  qui est responsable de traitement.
- **DPA / contrat de sous-traitance** doit être signé entre Showdesk
  et chaque Organization (à mettre en place côté commercial avant
  la GA).

### Fonctionnalités RGPD requises côté produit

#### Article 15 — Droit d'accès (export)

- Endpoint `POST /api/v1/contacts/{id}/export/` (admin org, async
  Celery, email avec ZIP).
- Contenu : profil + custom attrs + tickets + messages + attachments
  metadata + timeline events. Format JSON + CSV.

#### Article 17 — Droit à l'oubli

Choix design **anonymisation > suppression dure** :

- Suppression dure du Contact casse les threads de tickets (orphan
  messages, agents perdus). C'est aussi un risque légal en sens
  inverse (l'Organization a une obligation de conservation pour les
  litiges).
- Solution recommandée (cf. EDPB Coordinated Enforcement 2025) :
  **anonymisation**. Endpoint `POST /api/v1/contacts/{id}/anonymize/`
  qui :
  - Set `email = "anonymized-{uuid}@example.invalid"`.
  - Set `name = "Anonymized contact"`, `phone = ""`, `external_id = ""`.
  - Vide `attributes`.
  - Sur les `TicketMessage` du contact : remplace `body` par
    `"[Contenu supprimé à la demande du contact]"`.
  - Sur `Ticket.context_metadata` : whitelist (garde browser/os, vide
    URL et params).
  - Set un flag `is_anonymized = True` (immuable, audit log).
  - Conserve `Ticket.id` et la structure du thread (cohérence
    historique pour l'Organization).

#### Article 21 — Droit d'opposition (unsubscribe)

- Champ `Contact.is_unsubscribed` déjà au modèle. Si `True` : Showdesk
  bloque tout email transactionnel autre que ceux strictement
  nécessaires au traitement d'un ticket en cours.

#### Logging d'audit

- Table `ContactAuditLog` : qui (User), quoi (export / anonymize /
  edit_attribute), quand. Conservée 5 ans (durée prescription).

#### Rétention

- Config par Organization : `Organization.contact_retention_days` (null =
  illimité). Tâche Celery quotidienne anonymise les Contacts inactifs
  depuis N jours. Skippé au MVP, pré-câblé en migration.

#### Cookies / consentement widget

Le widget pose un cookie / localStorage `showdesk_session_id` pour
identifier la session. Aujourd'hui, c'est posé en automatique. Pour la
conformité ePrivacy / RGPD :

- Documenter que c'est un cookie "strictement nécessaire au service
  demandé par l'utilisateur" (= ouvrir un ticket) -> dispense de
  consentement préalable, **mais** la doc Showdesk doit le préciser
  noir sur blanc.
- Pour les events de tracking (page vue, etc.) à venir en Phase 2 :
  ceux-là **nécessitent consentement** (l'Organization fournit le bool
  via `Showdesk.init({ consent: true })`).

---

## 8. Import / sync

### MVP

- **CSV import** depuis la page Contacts : upload de fichier, mapping
  manuel des colonnes vers email/name/external_id/custom_attrs, dry-run
  preview, exécution avec rapport (créés / mis à jour / erreurs).
- **API publique** : endpoints CRUD + bulk identify (cf. §5).
- **Export CSV** depuis la liste Contacts (filtres appliqués).

### Phase 4

- **Webhook outbound** : POST vers une URL configurée par l'Organization
  à chaque create/update Contact / Company. Retry exponentiel.
- **Sync HubSpot / Attio natifs** : OAuth + sync incrémental
  bidirectionnel. C'est le killer feature pour les startups SaaS qui
  ont déjà leur CRM. À faire après que la base est solide.
- **Salesforce** : à reporter (entreprise, complexe, faible ROI pour
  le segment startups visé).

---

## 9. Segmentation et filtres

### MVP

- **Filtres simples** sur la liste Contact : recherche full-text email/name,
  filtre par Company, par custom attr `enum` ou `bool`, par lifecycle
  (`first_seen` <, `last_seen` >).
- **Saved views** : réutiliser le pattern `SavedView` déjà existant pour
  les tickets, étendu aux contacts.

### Phase 4

- **Segments dynamiques** : query builder à la Intercom
  (`plan == "pro" AND open_tickets_count >= 1 AND last_seen < 7d`).
  Stocké comme JSONField + compilation Django ORM.
- **Use cases segments** :
  - Broadcast (envoi groupé d'un message — Phase 5+, pas prioritaire
    pour un helpdesk).
  - Automation (auto-assign tickets de la Company `plan=enterprise` au
    team `Premium Support`).
  - Reporting (analytics filtrés par segment).

---

## 10. Priorisation MVP

### MVP — Phase 3 candidate

> Objectif : faire de Showdesk un helpdesk B2B SaaS sérieux, pas un
> simple ticket tracker. Sans Contact + Company, on est limité au
> support 1:1 sans contexte client.

- [ ] **P0 Backend** : modèles `Contact`, `Company`, `ContactAttributeDef`,
      `CompanyAttributeDef`, `ContactNote`. Migrations.
- [ ] **P0 Backend** : extension `WidgetSession` + `Ticket` avec FK
      `contact`. Migration de données qui peuple `contact` depuis
      `WidgetSession.email` / `external_user_id` existants.
- [ ] **P0 Backend** : endpoints CRUD contacts + companies + custom attrs
      (`/api/v1/contacts/`, `/api/v1/companies/`, `/api/v1/contact-attributes/`,
      `/api/v1/company-attributes/`).
- [ ] **P0 Backend** : extension widget identify (accepter `traits` +
      `company` payload), upsert Contact + Company au boot.
- [ ] **P0 Backend** : auto-link domaine email -> Company (best-effort).
- [ ] **P0 Backend** : endpoints RGPD (export + anonymize) sur Contact.
- [ ] **P0 Backend** : tests pytest sur tous les flux ci-dessus.
- [ ] **P0 Frontend** : page liste Contacts (recherche, filtres simples,
      pagination).
- [ ] **P0 Frontend** : page détail Contact (profil + timeline tickets +
      notes + custom attrs).
- [ ] **P0 Frontend** : page liste Companies + page détail Company.
- [ ] **P0 Frontend** : sidebar agent dans ticket detail montre Contact +
      Company avec liens.
- [ ] **P0 Frontend** : Settings -> Contact attributes (CRUD des
      `ContactAttributeDef`).
- [ ] **P0 Frontend** : Settings -> Company attributes (idem).

### Nice-to-have — Phase 3.5

- [ ] **P1** : import CSV Contacts + Companies (frontend + backend).
- [ ] **P1** : export CSV.
- [ ] **P1** : merge manuel de doublons (Contact only).
- [ ] **P1** : logo Company auto-fetch via `logo.dev` (Celery task).
- [ ] **P1** : audit log des actions sur Contact (consult, edit, delete).
- [ ] **P1** : Saved views pour la liste Contact.
- [ ] **P1** : extension API publique : `/api/v1/contacts/identify/` côté
      serveur (pas widget).

### Plus tard — Phase 4+

- [ ] **P2** : segments dynamiques (query builder).
- [ ] **P2** : intégration HubSpot / Attio (OAuth + sync bidirectionnel).
- [ ] **P2** : webhooks outbound contact.created / company.updated / etc.
- [ ] **P2** : enrichment provider hooks (PDL, Apollo, custom).
- [ ] **P2** : multi-Company par Contact (relâcher la contrainte).
- [ ] **P3** : timeline events arbitraires (`POST /api/v1/contacts/{id}/events/`)
      pour ingérer "user.signed_up", "subscription.upgraded", etc.
- [ ] **P3** : auto-merge intelligent sur identify.
- [ ] **P3** : rétention configurable + anonymisation auto.

---

## Sources

- [Intercom — Custom data attributes (CDAs)](https://www.intercom.com/help/en/articles/179-create-and-track-custom-data-attributes-cdas)
- [Intercom Developer — Data Attributes API](https://developers.intercom.com/docs/references/rest-api/api.intercom.io/data-attributes)
- [Intercom — Tracking user data](https://www.intercom.com/help/en/articles/320-tracking-user-data-in-intercom)
- [Intercom — Identity Verification (HMAC)](https://developers.intercom.com/installing-intercom/web/identity-verification)
- [Intercom — Migrating from HMAC to JWT](https://www.intercom.com/help/en/articles/10807823-migrating-from-identity-verification-to-messenger-security-with-jwts)
- [Zendesk — About custom fields and types](https://support.zendesk.com/hc/en-us/articles/4408838961562-About-custom-fields-and-custom-field-types)
- [Zendesk — Managing custom organization fields](https://support.zendesk.com/hc/en-us/articles/4410724977306-Managing-custom-organization-fields)
- [Zendesk — Understanding custom objects](https://support.zendesk.com/hc/en-us/articles/5914453843994-Understanding-custom-objects)
- [Zendesk Developer — Organizations API](https://developer.zendesk.com/api-reference/ticketing/organizations/organizations/)
- [HelpScout — Contact and Company Properties](https://docs.helpscout.com/article/1385-customer-properties)
- [HelpScout Developer — Update Customer Properties](https://developer.helpscout.com/mailbox-api/endpoints/properties/update/)
- [HelpScout — Beacon JavaScript API](https://developer.helpscout.com/beacon-2/web/javascript-api/)
- [Front — Contact custom fields](https://help.front.com/en/articles/2323)
- [Front — Use accounts and contacts in rules](https://help.front.com/en/articles/2202)
- [Front Developer — Custom Fields](https://dev.frontapp.com/reference/custom-fields)
- [Pylon — AI-native B2B Support](https://www.usepylon.com/)
- [Pylon — Best B2B Customer Support Platforms 2025](https://www.usepylon.com/blog/best-b2b-customer-support-platforms-2025)
- [Authencio — Pylon Review 2026](https://www.authencio.com/blog/pylon-review-the-b2b-saas-guide-to-modern-customer-support)
- [Plain — 15 Best Customer Support Software for B2B (2026)](https://www.plain.com/blog/customer-support-software)
- [TechCrunch — Plain raises $15M (2025)](https://techcrunch.com/2025/02/14/plain-pulls-in-15m-to-agregate-b2b-customer-services-chats-into-one-platform/)
- [Plain — API-first AI customer support platforms (2025)](https://www.plain.com/blog/ai-customer-support-api-first-platforms-2025)
- [BounceWatch — Clearbit alternatives after sunset](https://api.bouncewatch.com/blog/api-data/clearbit-alternative-enrichment-api)
- [Cleanlist — ZoomInfo vs Apollo vs Clearbit (2026)](https://www.cleanlist.ai/blog/zoominfo-apollo-clearbit-data-provider-comparison-2026)
- [Crustdata — Best People Data Labs alternatives (2026)](https://crustdata.com/blog/people-data-labs-alternatives-b2b-data-providers)
- [Apollo — Data enrichment tools 2026](https://www.apollo.io/insights/data-enrichment-tools)
- [EDPB — Coordinated Enforcement Action: Right to Erasure (2025)](https://www.edpb.europa.eu/system/files/2026-02/edpb_cef-report_2025_right-to-erasure_en.pdf)
- [CompliancePoint — GDPR Right to Erasure Enforcement Priority 2025](https://www.compliancepoint.com/privacy/gdpr-right-to-erasure-an-enforcement-priority-in-2025/)
- [ReedSmith — EDPB report on right to erasure: 2025 takeaways](https://www.reedsmith.com/our-insights/blogs/viewpoints/102mm9l/edpb-report-on-the-right-to-erasure-key-takeaways-from-the-2025-coordinated-enfo/)
- [Reform — GDPR-Compliant Data Deletion Best Practices](https://www.reform.app/blog/best-practices-gdpr-compliant-data-deletion)
- [Dropcontact — Duplicate detection in CRMs](https://www.dropcontact.com/detection-of-duplicates-contacts)
- [Stacksync — Attio CRM 2026 Review](https://www.stacksync.com/blog/attio-crm-2025-review-features-pros-cons-pricing)
- [Outfunnel — Attio + HubSpot 2-way sync](https://outfunnel.com/attio-hubspot-integration/)
- [TreasureData — Customer 360 in 2026](https://www.treasuredata.com/blog/customer-360)
