const MAX_PAGE = 100000;

/** What to ask the API for page `page`: one entry extra, so the page can tell whether another follows. */
export function pageRequest(page, size) {
  return { limit: size + 1, offset: (page - 1) * size };
}

export function pageResult(fetched, page, size) {
  return { entries: fetched.slice(0, size), hasNext: fetched.length > size, hasPrevious: page > 1 };
}

/** The page number in a query string such as "?page=3". Anything that is not a whole number from 1 up is page 1. */
export function pageFromQuery(search) {
  const value = new URLSearchParams(search).get("page");
  if (value === null || !/^\d+$/.test(value)) return 1;
  const page = Number(value);
  return page >= 1 && page <= MAX_PAGE ? page : 1;
}
