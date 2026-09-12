"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Expand, Search, SlidersHorizontal, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type Column<T> = {
  key: string;
  label: string;
  className?: string;
  render: (row: T) => React.ReactNode;
  searchValue?: (row: T) => unknown;
  filterValue?: (row: T) => unknown;
};

type Props<T> = {
  rows: T[];
  columns: Column<T>[];
  empty?: string;
  title?: string;
  searchable?: boolean;
  filterable?: boolean;
  paginated?: boolean;
  expandable?: boolean;
  pageSize?: number;
};

export function DataTable<T>({
  rows,
  columns,
  empty = "No records yet.",
  title = "Records",
  searchable = true,
  filterable = true,
  paginated = true,
  expandable = true,
  pageSize = 10,
}: Props<T>) {
  const [query, setQuery] = useState("");
  const [filterColumn, setFilterColumn] = useState("");
  const [filterValue, setFilterValue] = useState("");
  const [page, setPage] = useState(1);
  const [fullScreen, setFullScreen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const options = useMemo(() => {
    if (!filterColumn) return [];
    const column = columns.find((item) => item.key === filterColumn);
    if (!column) return [];
    return Array.from(new Set(rows.map((row) => String(column.filterValue?.(row) ?? column.searchValue?.(row) ?? (row as any)?.[column.key] ?? "")).filter(Boolean))).sort();
  }, [filterColumn, columns, rows]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      const matchesSearch = !needle || columns.some((column) => String(column.searchValue?.(row) ?? (row as any)?.[column.key] ?? "").toLowerCase().includes(needle));
      const selected = columns.find((column) => column.key === filterColumn);
      const matchesFilter = !filterColumn || !filterValue || String(selected?.filterValue?.(row) ?? selected?.searchValue?.(row) ?? (row as any)?.[filterColumn] ?? "") === filterValue;
      return matchesSearch && matchesFilter;
    });
  }, [rows, columns, query, filterColumn, filterValue]);

  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pages);
  const visible = paginated ? filtered.slice((safePage - 1) * pageSize, safePage * pageSize) : filtered;
  const activeFilters = Boolean(filterColumn || filterValue);

  const clearFilters = () => {
    setFilterColumn("");
    setFilterValue("");
    setPage(1);
  };

  const table = (
    <div className={cn("overflow-hidden rounded-2xl border border-border/70 bg-card/95 shadow-sm", fullScreen && "flex h-full flex-col rounded-none border-0")}>
      <div className="border-b border-border/70 bg-muted/10 p-3">
        <div className="flex flex-wrap items-center gap-2">
          {searchable && (
            <div className="relative min-w-[220px] flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input className="pl-9" value={query} onChange={(e) => { setQuery(e.target.value); setPage(1); }} placeholder={`Search ${title.toLowerCase()}…`} />
            </div>
          )}
          <span className="hidden text-xs font-semibold text-muted-foreground sm:inline">{filtered.length} {filtered.length === 1 ? "record" : "records"}</span>
          {filterable && (
            <Button type="button" variant={activeFilters ? "secondary" : "ghost"} size="sm" onClick={() => setFiltersOpen((value) => !value)} aria-expanded={filtersOpen}>
              <SlidersHorizontal className="h-4 w-4" />Filters{activeFilters ? " · active" : ""}
            </Button>
          )}
          {expandable && <Button type="button" size="icon" variant="ghost" aria-label={fullScreen ? "Close full-screen table" : "Open full-screen table"} onClick={() => setFullScreen(!fullScreen)}>{fullScreen ? <X className="h-4 w-4" /> : <Expand className="h-4 w-4" />}</Button>}
        </div>

        {filterable && filtersOpen && (
          <div className="mt-3 flex flex-wrap items-end gap-2 rounded-xl border border-border/70 bg-background p-3">
            <label className="grid min-w-[180px] gap-1 text-[10px] font-black uppercase tracking-wider text-muted-foreground">
              Filter field
              <select className="h-10 rounded-xl border bg-background px-3 text-sm font-semibold normal-case tracking-normal text-foreground" value={filterColumn} onChange={(e) => { setFilterColumn(e.target.value); setFilterValue(""); setPage(1); }}>
                <option value="">Choose a field…</option>
                {columns.map((column) => <option key={column.key} value={column.key}>{column.label}</option>)}
              </select>
            </label>
            {filterColumn && (
              <label className="grid min-w-[180px] gap-1 text-[10px] font-black uppercase tracking-wider text-muted-foreground">
                Value
                <select className="h-10 rounded-xl border bg-background px-3 text-sm font-semibold normal-case tracking-normal text-foreground" value={filterValue} onChange={(e) => { setFilterValue(e.target.value); setPage(1); }}>
                  <option value="">All values</option>
                  {options.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
            )}
            {activeFilters && <Button type="button" variant="ghost" size="sm" onClick={clearFilters}>Clear filters</Button>}
            <p className="w-full text-xs text-muted-foreground sm:w-auto sm:flex-1 sm:text-right">Filters are hidden until needed so the table stays focused on the records.</p>
          </div>
        )}
      </div>

      {!filtered.length ? (
        <div className="p-10 text-center">
          <p className="text-sm font-semibold text-muted-foreground">{empty}</p>
          {(query || activeFilters) && <Button className="mt-3" type="button" variant="ghost" size="sm" onClick={() => { setQuery(""); clearFilters(); }}>Clear search and filters</Button>}
        </div>
      ) : (
        <div className={cn("overflow-auto", fullScreen && "flex-1")}>
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead className="sticky top-0 z-10 bg-muted"><tr>{columns.map((column) => <th key={column.key} className={cn("border-b border-border/70 px-4 py-3 text-xs font-black uppercase tracking-[.08em] text-muted-foreground", column.className)}>{column.label}</th>)}</tr></thead>
            <tbody>{visible.map((row, index) => <tr key={index} className="border-b border-border/60 transition last:border-0 hover:bg-muted/25">{columns.map((column) => <td key={column.key} className={cn("px-4 py-3 align-middle text-foreground/85", column.className)}>{column.render(row)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}

      {paginated && filtered.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t p-3 text-sm text-muted-foreground">
          <span>Showing {(safePage - 1) * pageSize + 1}–{Math.min(safePage * pageSize, filtered.length)} of {filtered.length}</span>
          <div className="flex items-center gap-2">
            <Button type="button" size="icon" variant="ghost" disabled={safePage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button>
            <span className="text-xs font-semibold">Page {safePage} of {pages}</span>
            <Button type="button" size="icon" variant="ghost" disabled={safePage >= pages} onClick={() => setPage((value) => Math.min(pages, value + 1))} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>
      )}
    </div>
  );

  return fullScreen ? <div className="fixed inset-0 z-[80] bg-background p-4">{table}</div> : table;
}
