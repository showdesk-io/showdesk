# frozen_string_literal: true

# Run by postal_domains.py in Postal's web container, on stdin:
#
#   timeout -s KILL <n> bundle exec rails runner - <action> <organization> <server> <name or uuid> <protected>
#
# Actions: create (a name), show, check, delete (a uuid). Only the domains of
# the given server are read or written; postal_domains.py only asks for the
# uuids of the domains it created, and tells an existing domain (200) that is
# its own from one that isn't. <protected>: comma-separated domain names that
# are never created, shown, checked nor deleted, nor their subdomains. Prints
# one line:
#
#   SHOWDESK_RESULT {"status": 200|201|204, "domain": {...}}
#   SHOWDESK_RESULT {"error": "not_found" | "protected" | "exists" | "rejected" | "no_server" | "invalid" | "failed", ...}
#
# Written against Postal 3.3 (app/models/domain.rb, has_dns_checks.rb).

require "json"

RESULT_PREFIX = "SHOWDESK_RESULT "
LABEL = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
NAME_RE = /\A(?=.{1,253}\z)(?:#{LABEL}\.)+(?![0-9]+\z)#{LABEL}\z/
UUID_RE = /\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z/
PERMALINK_RE = /\A[a-z0-9][a-z0-9-]{0,63}\z/

def emit(payload)
  $stdout.puts(RESULT_PREFIX + JSON.generate(payload))
  $stdout.flush
end

# The records to publish, fully qualified, and Postal's last DNS check.
def domain_state(domain)
  dns = Postal::Config.dns
  records = [
    # Postal's own spf_record adds "a mx": the domain's hosts don't send here.
    { kind: "spf", type: "TXT", name: domain.name, value: "v=spf1 include:#{dns.spf_include} ~all" },
    { kind: "dkim", type: "TXT", name: "#{domain.dkim_record_name}.#{domain.name}", value: domain.dkim_record },
  ]
  if dns.custom_return_path_prefix.present?
    records << { kind: "return_path", type: "CNAME", name: domain.return_path_domain, value: dns.return_path_domain }
  end
  {
    id: domain.uuid,
    name: domain.name,
    records: records,
    status: {
      checked_at: domain.dns_checked_at&.utc&.iso8601,
      dkim: domain.dkim_status,
      dkim_error: domain.dkim_error,
      spf: domain.spf_status,
      spf_error: domain.spf_error,
      return_path: domain.return_path_status,
      return_path_error: domain.return_path_error
    }
  }
end

def protected?(name, protected_names)
  protected_names.any? { |entry| name == entry || name.end_with?(".#{entry}") }
end

def create(server, name)
  # The organization's domains count for the server too: never Showdesk's.
  return emit(error: "exists", detail: "organization") if server.organization.domains.exists?(name: name)

  # Returned as it is (never verified here): postal_domains.py only takes it
  # if it created it.
  domain = server.domains.find_by(name: name)
  return emit(status: 200, domain: domain_state(domain)) if domain

  domain = server.domains.build(name: name, verification_method: "DNS", outgoing: true, incoming: false)
  domain.verified_at = Time.now
  if domain.save
    emit(status: 201, domain: domain_state(domain))
  elsif (existing = server.domains.find_by(name: name))
    # Created meanwhile by another call.
    emit(status: 200, domain: domain_state(existing))
  else
    emit(error: "rejected", detail: domain.errors.full_messages.join(", "))
  end
end

begin
  action, organization, server_permalink, arg, protected_arg = ARGV
  unless PERMALINK_RE.match?(organization.to_s) && PERMALINK_RE.match?(server_permalink.to_s)
    emit(error: "invalid", detail: "permalinks")
    exit 1
  end
  protected_names = protected_arg.to_s.split(",")
  unless protected_names.all? { |entry| NAME_RE.match?(entry) }
    emit(error: "invalid", detail: "protected")
    exit 1
  end

  server = Server.present
                 .joins(:organization)
                 .where(organizations: { permalink: organization, deleted_at: nil })
                 .find_by(permalink: server_permalink)
  if server.nil?
    emit(error: "no_server", detail: "#{organization}/#{server_permalink}")
    exit 1
  end

  if action == "create"
    unless NAME_RE.match?(arg.to_s)
      emit(error: "invalid", detail: "name")
      exit 1
    end
    if protected?(arg, protected_names)
      emit(error: "protected")
    else
      create(server, arg)
    end
  elsif %w[show check delete].include?(action)
    unless UUID_RE.match?(arg.to_s)
      emit(error: "invalid", detail: "uuid")
      exit 1
    end
    domain = server.domains.find_by(uuid: arg)
    if domain.nil?
      emit(error: "not_found")
    elsif protected?(domain.name.downcase, protected_names)
      emit(error: "protected")
    elsif action == "delete"
      domain.destroy!
      emit(status: 204)
    else
      # Postal signs with the domain's key only once its DKIM checked OK, and
      # only re-checks hourly the domains it has checked once.
      domain.check_dns(:manual) if action == "check"
      emit(status: 200, domain: domain_state(domain))
    end
  else
    emit(error: "invalid", detail: "action")
    exit 1
  end
rescue StandardError => e
  emit(error: "failed", detail: "#{e.class}: #{e.message}"[0, 500])
  exit 1
end
