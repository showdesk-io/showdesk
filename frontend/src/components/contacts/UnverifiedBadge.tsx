/**
 * The states of a contact's identity, as badges.
 */

/** Marks an email nobody has proven: it can't be trusted as this contact's identity. */
export function UnverifiedBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-800"
      title="This email has not been verified"
    >
      Unverified
    </span>
  );
}

export function VerifiedBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800"
      title="This email has been verified"
    >
      Verified
    </span>
  );
}

export function AnonymizedBadge() {
  return (
    <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
      Anonymized
    </span>
  );
}
