/**
 * Stands in for the contact and company detail pages. Without a route, the whole app
 * including its sidebar goes blank on the links the lists give.
 */

import { Link } from "react-router";

export function DetailPlaceholder({ backTo, backLabel }: { backTo: string; backLabel: string }) {
  return (
    <div className="p-6 text-center text-gray-500">
      <p>This page isn't available yet.</p>
      <Link to={backTo} className="mt-2 inline-block text-sm text-primary-700 hover:underline">
        Back to {backLabel}
      </Link>
    </div>
  );
}
