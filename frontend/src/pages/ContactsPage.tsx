/**
 * The Contacts and Companies lists, as two tabs driven by the route.
 */

import { useLocation } from "react-router";
import { CompanyList } from "@/components/contacts/CompanyList";
import { ContactList } from "@/components/contacts/ContactList";

export function ContactsPage() {
  const { pathname } = useLocation();
  return pathname.startsWith("/companies") ? <CompanyList /> : <ContactList />;
}
