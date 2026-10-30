/**
 * Marks an email nobody has proven: it can't be trusted as this contact's identity.
 */

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
