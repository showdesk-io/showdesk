# Création de ticket par un agent (back-office Showdesk)

> Brainstorm — 2026-05-01
> Auteur: recherche assistée
> Statut: à valider produit

## TL;DR

- Aujourd'hui dans Showdesk, **un ticket ne peut être créé que par un enduser via le widget** (`widget_submit`, `widget_message`). L'agent ne peut que répondre. C'est un trou fonctionnel majeur dès qu'un canal sort du widget : appel téléphonique, LinkedIn, salon, incident proactif, migration depuis un ancien outil.
- L'enum `Ticket.Source` contient déjà `WIDGET / EMAIL / API / AGENT` — donc le **modèle est en grande partie prêt**, mais aucune route ni UI n'utilise `AGENT`. Il faut surtout : (a) activer le `POST /api/v1/tickets/` authentifié pour les agents, (b) ajouter un **flow de recherche/création de contact**, (c) clarifier le **canal d'origine** (téléphone, email manuel, autre), (d) gérer le **mode silencieux vs reach-out** (envoyer ou non un email à l'enduser), (e) tracer **qui a créé pour qui** (audit).
- Tous les concurrents majeurs (Zendesk, Intercom, Freshdesk, Help Scout, Front, Crisp) font la **distinction submitter ≠ requester** + un champ `channel/source`. Zendesk a la sémantique la plus propre : `submitter_id` (l'agent), `requester_id` (le client), et un comportement "public ticket vs private ticket" pour décider si l'enduser est notifié.
- Recommandation : ajouter `Ticket.created_by` (FK User agent), basculer la default du champ `source` à un set élargi (`web_widget`, `email`, `phone`, `manual`, `api`, `chat_external`, `import`), introduire un `Contact` léger (ou réutiliser `User role=END_USER`) avec dédoublonnage par email/external_user_id, et exposer un endpoint `POST /api/v1/tickets/` complet pour la création back-office. Phase 1 = UX simple "New ticket" sans contact ; Phase 2 = picker contact + outbound email ; Phase 3 = bulk import + AI prefill.

---

## 1. Cas d'usage prioritaires Showdesk

Classés par fréquence attendue dans la cible **startups SaaS** :

| Priorité | Cas d'usage | Fréquence cible | Canal d'origine |
|---|---|---|---|
| P0 | Appel entrant — l'agent prend des notes pendant/après l'appel | Hebdo pour les startups B2B | `phone` |
| P0 | Demande venue d'un canal non intégré (LinkedIn DM, X, salon, démo) | Hebdo | `manual` |
| P1 | Suivi proactif après incident infra — on crée 5–50 tickets pour les clients impactés | Mensuel mais critique | `proactive` ou `manual` |
| P1 | Migration ponctuelle depuis Intercom/Zendesk/Front à l'arrivée du client sur Showdesk | One-shot, gros volume | `import` |
| P2 | Création par API (intégration Slack, monitoring, formulaire externe) | Variable | `api` |
| P2 | Création de tâche interne / suivi qui n'a pas de client externe identifié | Faible | `internal` |

Spécificités Showdesk :
- **Multi-tenant** : la création doit être scopée à l'org active (déjà le cas via `get_active_org`).
- **OTP-only auth** : pas de mot de passe, donc le contact créé pour l'enduser ne peut pas recevoir d'invitation classique. Pour le widget, le retour de l'enduser passe par le **lien magique d'email** (à concevoir) ou par un widget identifié via `external_user_id` côté client.
- **Pas de modèle Company** aujourd'hui. À garder en tête pour la suite (B2B grouping).

---

## 2. Comparatif concurrents

### Zendesk

Modèle de référence pour la sémantique `submitter` vs `requester`. Quand un agent crée un ticket via l'UI, **l'agent est le submitter, le client est le requester** ; le premier commentaire est attribué à l'agent et le ticket affiche "created on behalf of". Idem en API via `submitter_id`. Distinction clé : **public ticket** (le client est notifié et voit le ticket dans son portail) vs **private ticket** (création silencieuse, le client n'est notifié que si on le bascule en public). L'API supporte aussi un header `Idempotency-Key` (TTL 2 h) pour éviter les doublons en cas de retry. Audit log au niveau ticket : "Trigger X fired on ticket #123 at 2:30 PM, changing status from New to Open" — niveau de granularité visé.

Sources : [Creating a ticket on behalf of the requester](https://support.zendesk.com/hc/en-us/articles/4408882462618-Creating-a-ticket-on-behalf-of-the-requester), [Tickets API](https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/), [Idempotency keys](https://www.eesel.ai/blog/zendesk-api-idempotency-keys), [Audit logs](https://developer.zendesk.com/api-reference/ticketing/account-configuration/audit_logs/), [Audit log events 2026](https://www.eesel.ai/blog/zendesk-audit-log-events).

### Intercom

UX très fluide : depuis la **fiche contact**, bouton **New Conversation** ; on choisit le canal (chat, email, post in-app, phone). Pour la création depuis zéro, **Outbound > New message** permet du one-to-one ou du broadcast. **Intercom Phone** crée automatiquement une conversation à chaque appel sortant et associe le contact si le numéro matche. Côté AI 2026 : **Fin AI Copilot** génère un résumé de conversation, suggère un brouillon de réponse, et **Intercom AI génère des résumés d'appels téléphoniques** automatiquement postés au ticket. La déduplication contact se fait sur `user_id` + email, mais Intercom **ne permet pas de merger deux contacts** nativement (limite documentée).

Sources : [Outbound chat](https://www.intercom.com/help/en/articles/3292781-create-outbound-chat-and-post-messages), [Make outbound calls](https://www.intercom.com/help/en/articles/8488920-make-outbound-calls), [AI phone call summaries](https://www.intercom.com/changes/en/82213-ai-generated-phone-call-summaries), [Initiate conversation from admin](https://community.intercom.com/api-webhooks-23/initiate-a-conversation-from-an-admin-to-a-user-1888), [Contacts FAQs](https://www.intercom.com/help/en/articles/8827723-contacts-faqs).

### Freshdesk

UX classique "+ New ticket" depuis le portail agent. Force est sur l'**intégration Freshcaller** (téléphonie native) : à la fin d'un appel, l'agent a un bouton "Create ticket" qui pré-remplit notes + enregistrement audio en private note. Bonne approche du "phone -> ticket" qu'on devra mimer si on intègre une téléphonie. Le ticket porte un champ `source` enum (Email, Portal, Phone, Chat, Mobihelp, Feedback Widget, Outbound Email, Ecommerce, etc.).

Sources : [Phone channel](https://support.freshdesk.com/support/solutions/articles/229608-adding-a-phone-channel-to-your-freshdesk), [Convert calls to tickets](https://support.freshdesk.com/support/solutions/articles/169203-converting-phone-calls-to-tickets), [Easily creating new ticket](https://fgrade.com/freshdesk/getting-started-support-channels-new-ticket).

### Help Scout

UX "New Conversation" très épurée. Champ `To:` accepte le format **`FirstName LastName <email@domain.com>`** : si le contact n'existe pas, **il est créé à la volée** en même temps que la conversation (zéro friction, pas de modal contact séparé). Possibilité de **pré-remplir via URL** (`?customer=...&subject=...`) — astuce intéressante pour les liens depuis CRM. Conversation peut être créée comme **email standard** (envoyé tout de suite à l'enduser) ou comme **note** (uniquement interne). Bonne ergonomie à imiter pour Showdesk.

Sources : [Create a New Conversation](https://docs.helpscout.com/article/12-create-a-new-conversation), [Create with pre-filled data](https://docs.helpscout.com/article/119-pre-fill), [Change customer on conversation](https://docs.helpscout.com/article/437-change-customer), [Create Conversation API](https://developer.helpscout.com/mailbox-api/endpoints/conversations/create/).

### Front

Bouton **Compose** unique au top de l'inbox = "one-stop-shop" multi-canal : on choisit le canal (email, SMS, WhatsApp, custom channel) **après** avoir cliqué Compose, puis on rédige. Réglage par utilisateur "Send in new conversation" pour forcer un nouveau thread plutôt que de répondre dans un thread existant. Utile pour Showdesk : montre qu'**un seul bouton "New" suffit** si la sélection du canal est intégrée dans le composer.

Sources : [Compose, send, customize](https://help.front.com/en/articles/2218), [New conversations](https://help.front.com/en/articles/2310), [Composer](https://help.frontapp.com/t/m2298k/understanding-fronts-composer).

### Crisp

Création **depuis la fiche Contact** ("Compose" sur le profil), ce qui pré-remplit automatiquement les infos. Pas de modal contact séparé. Petit ajout 2025 : **smart autocomplete** sur les participants. Approche minimaliste, valable pour la phase 1 de Showdesk.

Sources : [How to create a new conversation](https://help.crisp.chat/en/article/how-can-i-create-a-new-conversation-lw3wp8/), [October 2025 update](https://crisp.chat/en/blog/october-2025-product-update/).

### Plain (référence pour startups B2B)

Plain est **API-first** et oriente vers le **bulk import** comme cas standard à l'onboarding (CSV ou prebuilt importer). Crée une "thread" plutôt qu'un "ticket". Sa philosophie est plus proche de Showdesk (startups SaaS) : peu de friction, beaucoup d'API, intégrations Slack/Teams natives. Côté création manuelle agent : moins documentée publiquement, mais tout passe par GraphQL avec `createThread`, `addNoteToThread`, etc. À surveiller pour l'API design.

Sources : [Plain.com](https://www.plain.com/), [Plain MCP](https://mcp.composio.dev/plain), [TechCrunch coverage](https://techcrunch.com/2022/11/09/plain-is-a-new-customer-support-tool-with-a-focus-on-api-integrations/).

### Pylon

AI-native B2B support. Met l'accent sur la **conversion automatique** Slack/Teams -> ticket plutôt que sur la création manuelle agent. Détecte les mots-clés ("bug", "broken", "help") et propose de créer un ticket. Moins pertinent pour notre P0 mais utile pour la roadmap AI agent.

Sources : [Pylon AI helpdesk](https://www.usepylon.com/blog/ai-help-desk), [Microsoft Teams guide](https://www.usepylon.com/blog/microsoft-teams-helpdesk-2025-guide).

---

## 3. Modèle de données recommandé

État actuel (`backend/apps/tickets/models.py`) :

- `Ticket.source = TextChoices(WIDGET, EMAIL, API, AGENT)` ✅ existe, mais limité.
- `Ticket.requester` (FK User, nullable) ✅ — peut servir de "requester".
- `Ticket.requester_name` / `requester_email` (CharField/EmailField) ✅ — pour les non-users.
- `Ticket.assigned_agent` ✅.
- **Pas de `created_by_agent` / `submitter`** ❌.
- **Pas de modèle `Contact`** distinct. Les endusers sont `User(role=END_USER)` ou `WidgetSession` ou des strings.
- **Pas d'audit log structuré** ❌.
- **Pas de `is_outbound` / silent flag** ❌.

### Changements proposés sur `Ticket`

```python
class Ticket(TimestampedModel):

    class Source(models.TextChoices):
        WEB_WIDGET = "web_widget", "Web widget"      # remplace WIDGET (rétro-compat: alias)
        EMAIL      = "email", "Email"
        PHONE      = "phone", "Phone call"           # NOUVEAU
        MANUAL     = "manual", "Manual (agent)"      # NOUVEAU — canal externe non intégré
        API        = "api", "API"
        IMPORT     = "import", "Import"              # NOUVEAU — migration / bulk
        CHAT_EXT   = "chat_external", "External chat"  # NOUVEAU — Slack, Teams, WhatsApp...

    # NOUVEAU — l'agent qui a cliqué "Create ticket".
    # Différent de assigned_agent (qui peut être nul ou autre).
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_tickets",
        help_text="Agent who manually created this ticket. Null for widget/email/api.",
    )

    # NOUVEAU — booléen de notification.
    # True = on n'envoie PAS d'email d'accusé réception au requester (proactive incident,
    # note interne, ticket "private" à la Zendesk).
    is_silent = models.BooleanField(
        default=False,
        help_text="If true, do not send any outbound notification to the requester on create.",
    )

    # NOUVEAU — direction de la conversation pour la métrique outbound.
    direction = models.CharField(
        max_length=10,
        choices=[("inbound", "Inbound"), ("outbound", "Outbound")],
        default="inbound",
    )

    # OPTIONNEL — métadonnées propres au canal manuel
    source_metadata = models.JSONField(
        default=dict, blank=True,
        help_text="Channel-specific metadata: {phone_number, call_duration, linkedin_url, ...}",
    )
```

**Note rétro-compat** : on peut garder `WIDGET = "widget"` en synonyme et migrer les valeurs existantes via une data migration. Préférable de **garder le slug court "widget"** plutôt que `web_widget` pour ne pas casser le widget JS et les tests existants — décision à arbitrer.

### Concept `Contact` — option légère vs option complète

L'option à valider produit. Aujourd'hui `User(role=END_USER)` joue ce rôle, mais c'est lourd : un contact n'a pas besoin d'un compte avec password/OTP.

**Option A — minimaliste (recommandée pour Phase 1)** : ne **rien** ajouter au modèle. Réutiliser `requester_name` + `requester_email` + `external_user_id` (déjà sur `Ticket`). Le picker UI cherche dans les `Ticket` + `WidgetSession` + `User(role=END_USER)` existants par email. C'est suffisant pour 90 % des cas.

**Option B — modèle Contact dédié (Phase 2 ou 3)** : nouveau modèle `Contact` (ou `EndUser`) dans `apps.contacts`, avec :

```python
class Contact(TimestampedModel):
    organization = FK(Organization)
    email = EmailField(blank=True, db_index=True)
    phone = CharField(blank=True, db_index=True)
    name  = CharField(blank=True)
    external_user_id = CharField(blank=True, db_index=True)
    company = FK("Company", null=True, blank=True)  # B2B grouping (futur)
    metadata = JSONField(default=dict)
    user = FK(User, null=True, blank=True)  # lié si l'enduser a un compte plein
    class Meta:
        unique_together = [("organization", "email"), ("organization", "external_user_id")]
```

Dans ce cas `Ticket.requester` deviendrait `FK(Contact)` plutôt que `FK(User)` — gros refacto. À ne pas faire en Phase 1.

### Audit log

Phase 1 : il **suffit** de logger `created_by` et `created_at` sur `Ticket`. Ça répond à "qui a créé pour qui le date Z".

Phase 2 : modèle `TicketAuditEvent` générique pour les transitions (status change, assignation, merge, etc.) — voir [Zendesk Ticket Audit events](https://developer.zendesk.com/documentation/ticketing/reference-guides/ticket-audit-events-reference/) pour la granularité.

---

## 4. UX recommandée — flow de création

### Phase 1 (MVP, ~1 sprint)

**Bouton "+ Nouveau ticket"** dans `AppLayout` (header ou sidebar), à côté du sélecteur d'org.

Modal en 1 écran :

1. **Titre** (obligatoire, autofocus)
2. **Description** (markdown, comme la composer agent)
3. **Contact** — input avec autocomplete :
   - Recherche server-side dans (Tickets.requester_email distincts) + (WidgetSession.email) + (User.email où role=END_USER), match sur `name` ou `email` ou `external_user_id`.
   - Format Help-Scout-style accepté : `Jean Dupont <jean@acme.com>` -> crée le contact à la volée si non trouvé.
   - Optionnel à la soumission si `is_silent=True` (cas "note interne / ticket de suivi sans client").
4. **Canal** (radio ou select) : Téléphone / Email manuel / Autre canal / Suivi proactif (4 cases couvrent 95 % des cas).
5. **Notifier le contact ?** (toggle) :
   - ON par défaut si email présent et canal ≠ "Suivi proactif" — enverra le mail "On a ouvert un ticket pour vous".
   - OFF par défaut si pas d'email ou si canal = "Suivi proactif".
6. **Priorité** + **Type d'issue** + **Tags** + **Assigné à** (tous optionnels, pré-remplis par défaut).

Bouton submit : **Créer le ticket**. Redirige vers la page détail du ticket, focus sur la zone de message pour pouvoir ajouter immédiatement les notes/captures.

### Phase 2

- **Création depuis la fiche contact** (quand on aura une page Contact). Pré-remplit le contact.
- **Pré-remplissage par URL** : `?contact_email=...&title=...&source=phone` (utile depuis CRM externe ou favori navigateur).
- **Templates de ticket** : "Incident infra", "Demo follow-up" — pré-remplit titre + description + tags.
- **Outbound first message** : en mode "reach-out", l'agent peut envoyer directement le premier email (avec macro/canned response) au lieu d'un simple accusé réception.
- **Bulk creation** : import CSV (mapping email/title/description/tags) + API bulk endpoint avec idempotency key.

### Phase 3

- **AI prefill** : coller un transcript d'appel ou un email forward, l'IA propose titre + description + priorité + tags. Inspiré d'[Intercom AI phone call summaries](https://www.intercom.com/changes/en/82213-ai-generated-phone-call-summaries).
- **Browser extension** "Add to Showdesk" depuis LinkedIn / Gmail / Slack.

---

## 5. Impact API publique et webhooks

### Endpoint actuel

`TicketViewSet` est déjà un `ModelViewSet` avec `IsAuthenticated`. Donc `POST /api/v1/tickets/` **existe déjà** côté agent ; il manque juste l'UI et quelques garanties. À vérifier :

- Le `TicketSerializer` utilisé en write-mode accepte-t-il les nouveaux champs `created_by`, `is_silent`, `direction`, `source` ? Aujourd'hui non — il faut les ajouter aux `fields` et garder en `read_only_fields` ce qui doit l'être.
- `perform_create` met `organization` et `reference`, mais ne met pas `created_by=request.user` ni `source=Ticket.Source.MANUAL` par défaut. À ajouter.
- L'envoi de mail (`send_ticket_created_email.delay`) part **toujours** : à conditionner par `not ticket.is_silent`.

### API publique (pour intégrations tierces)

S'aligner sur Zendesk :

- Header `Idempotency-Key: <uuid>` — TTL 2 h, cache la réponse pour les retries. Voir [Zendesk idempotency](https://www.eesel.ai/blog/zendesk-api-idempotency-keys).
- Body :
  ```json
  {
    "title": "...",
    "description": "...",
    "source": "phone",
    "is_silent": false,
    "requester": { "email": "...", "name": "...", "external_user_id": "..." },
    "submitter_id": "<agent-uuid>",   // si créé via OAuth app, sinon implicite via session
    "priority": "high",
    "tags": ["incident-2026-05"],
    "assigned_agent_id": "...",
    "metadata": { "call_id": "...", "duration_s": 320 }
  }
  ```
- Le champ `requester` est polymorphe : on cherche `email` ou `external_user_id` dans l'org ; si non trouvé, on crée à la volée.
- Réponse 201 avec le ticket complet, ou 200 si idempotency hit.

### Webhooks

Le webhook `ticket.created` doit inclure :
- `source` (canal d'origine)
- `is_silent`
- `created_by_agent_id` (null si bot/widget)
- `direction`

Cas spécial : un **`ticket.created.outbound`** distinct (ou un flag dans le payload) permet aux clients d'appliquer des automatisations différentes selon que l'origine est une demande client ou une initiative agent.

---

## 6. Permissions et sécurité

- **Qui peut créer ?** Tout `User` avec `role IN (admin, agent)` dans l'org active. Pas les endusers (déjà bloqué par le widget actuel). À vérifier qu'un `agent` ne peut pas créer un ticket pour une **autre org** (le `get_active_org` doit le garantir, mais ajouter un test).
- **Qui peut spécifier `created_by` arbitraire ?** Aucun agent normal ; seul un service-account / admin via API publique avec `submitter_id` explicite. Sinon `created_by = request.user` toujours.
- **Audit** : log `created_by`, `created_at`, `source`, `is_silent`, `direction` dans le ticket lui-même + un événement `TicketAuditEvent` (Phase 2).
- **Quota / rate limit** : la création back-office est généralement low-volume (humain), mais le bulk import et l'API doivent passer par des throttles dédiés (déjà des throttles widget en place, modèle réutilisable).

---

## 7. Recommandations de priorisation

| Phase | Effort | Valeur | Contenu |
|---|---|---|---|
| **P1 — MVP créa manuelle** | ~3-5 j | Très élevée | Migration: `Ticket.created_by`, `is_silent`, `direction`, élargir `Source` enum. UI: bouton "+ New ticket" avec modal simple (title, description, contact email, canal, notify toggle, assignee, priority). Backend: `perform_create` set `created_by=request.user` + `source=manual` par défaut. `send_ticket_created_email` conditionné par `not is_silent`. Tests. |
| **P2 — Polish UX + outbound** | ~5-8 j | Élevée | Picker contact server-side avec autocomplete (recherche dans tickets/sessions/users). Pré-remplissage URL. Premier message outbound (template/macro) à la création. Audit log basique (event "ticket_created_by_agent"). |
| **P3 — Bulk + API publique** | ~5 j | Moyenne | Idempotency-Key sur API. Import CSV (UI Settings > Import). Endpoint bulk `POST /api/v1/tickets/bulk/`. Webhooks enrichis. |
| **P4 — AI prefill** | ~10 j | Moyenne (différenciante) | Coller un transcript / email -> auto-suggestion titre/description/priorité/tags. Inspiration : [Intercom AI call summaries](https://www.intercom.com/changes/en/82213-ai-generated-phone-call-summaries), [helpdesk copilots](https://www.eesel.ai/blog/helpdesk-copilot). Probablement après le pivot widget WhatsApp-style. |
| **P5 — Modèle Contact dédié** | ~10-15 j | À reporter | Refacto `requester` en FK(Contact). À aligner avec le besoin B2B/Company. Pas avant qu'on ait des clients qui demandent. |

**Décision suggérée** : faire **P1 maintenant** (déblocant pour les startups B2B early-adopter), planifier **P2 dans 2-4 semaines** une fois P1 en prod. Reporter P3-P5.

---

## Annexe — sources web consultées

- Zendesk
  - [Creating a ticket on behalf of the requester](https://support.zendesk.com/hc/en-us/articles/4408882462618-Creating-a-ticket-on-behalf-of-the-requester)
  - [Tickets API](https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/)
  - [How to use Zendesk API idempotency keys (eesel)](https://www.eesel.ai/blog/zendesk-api-idempotency-keys)
  - [Audit Logs API](https://developer.zendesk.com/api-reference/ticketing/account-configuration/audit_logs/)
  - [Audit log events 2026 (eesel)](https://www.eesel.ai/blog/zendesk-audit-log-events)
  - [Ticket Audit events reference](https://developer.zendesk.com/documentation/ticketing/reference-guides/ticket-audit-events-reference/)
  - [Private ticket creation](https://support.zendesk.com/hc/en-us/articles/4408842918298-Enabling-and-disabling-private-ticket-creation)
- Intercom
  - [Create outbound chat](https://www.intercom.com/help/en/articles/3292781-create-outbound-chat-and-post-messages)
  - [Make outbound calls](https://www.intercom.com/help/en/articles/8488920-make-outbound-calls)
  - [Initiate conversation from admin](https://community.intercom.com/api-webhooks-23/initiate-a-conversation-from-an-admin-to-a-user-1888)
  - [Contacts FAQs](https://www.intercom.com/help/en/articles/8827723-contacts-faqs)
  - [AI-Generated Phone Call Summaries](https://www.intercom.com/changes/en/82213-ai-generated-phone-call-summaries)
  - [Intercom AI Review 2026](https://reply.io/blog/intercom-ai-review/)
- Freshdesk
  - [Phone channel](https://support.freshdesk.com/support/solutions/articles/229608-adding-a-phone-channel-to-your-freshdesk)
  - [Convert phone calls to tickets](https://support.freshdesk.com/support/solutions/articles/169203-converting-phone-calls-to-tickets)
  - [Easily creating new ticket from agent portal (FGRADE)](https://fgrade.com/freshdesk/getting-started-support-channels-new-ticket)
- Help Scout
  - [Create a New Conversation](https://docs.helpscout.com/article/12-create-a-new-conversation)
  - [Pre-fill data via URL](https://docs.helpscout.com/article/119-pre-fill)
  - [Change customer on conversation](https://docs.helpscout.com/article/437-change-customer)
  - [Create Conversation API](https://developer.helpscout.com/mailbox-api/endpoints/conversations/create/)
- Front
  - [How to compose, send, customize messages](https://help.front.com/en/articles/2218)
  - [New conversations](https://help.front.com/en/articles/2310)
  - [Understanding Front's composer](https://help.frontapp.com/t/m2298k/understanding-fronts-composer)
- Crisp
  - [How can I create a new conversation?](https://help.crisp.chat/en/article/how-can-i-create-a-new-conversation-lw3wp8/)
  - [October 2025 product update](https://crisp.chat/en/blog/october-2025-product-update/)
- Plain
  - [Plain.com](https://www.plain.com/)
  - [Plain MCP integration](https://mcp.composio.dev/plain)
  - [Plain on TechCrunch](https://techcrunch.com/2022/11/09/plain-is-a-new-customer-support-tool-with-a-focus-on-api-integrations/)
- Pylon
  - [AI Help Desk](https://www.usepylon.com/blog/ai-help-desk)
  - [MS Teams helpdesk 2025](https://www.usepylon.com/blog/microsoft-teams-helpdesk-2025-guide)
- Transverses
  - [Guide to Customer Help Desk APIs (Merge.dev)](https://www.merge.dev/blog/guide-to-help-desk-apis)
  - [What is a helpdesk copilot? (eesel)](https://www.eesel.ai/blog/helpdesk-copilot)
  - [Top AI Copilot Tools for Customer Support 2026 (Fin)](https://fin.ai/learn/ai-copilot-tools)
