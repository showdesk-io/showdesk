/**
 * The page of a paginated list, which belongs to the filters it was chosen under:
 * page 1 for any others. Derived rather than reset, so that a request for the new
 * filters never goes out with the old page.
 */

import { useState } from "react";

export function useFilterPage(filtersKey: string) {
  const [chosen, setChosen] = useState({ filtersKey, page: 1 });
  const page = chosen.filtersKey === filtersKey ? chosen.page : 1;
  const setPage = (next: number) => setChosen({ filtersKey, page: next });
  return [page, setPage] as const;
}
