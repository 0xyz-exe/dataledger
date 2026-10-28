import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../app/AuthContext';
import { discrepancies } from '../../lib/api';
import { AlertCircle, CheckCircle, X } from 'lucide-react';

const CATEGORIES = ['matched', 'missing_in_a', 'missing_in_b', 'amount_mismatch', 'date_mismatch', 'reference_mismatch', 'ambiguous_match', 'duplicate_candidate', 'invalid_record'];
const STATUSES = ['open', 'reviewed', 'resolved', 'reopened'];

function CategoryBadge({ category }: { category: string }) {
  const cls: Record<string, string> = {
    matched: 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400',
    missing_in_a: 'bg-amber-50 text-amber-700',
    missing_in_b: 'bg-amber-50 text-amber-700',
    amount_mismatch: 'bg-red-50 text-red-700',
    date_mismatch: 'bg-orange-50 text-orange-700',
    ambiguous_match: 'bg-purple-50 text-purple-700',
    duplicate_candidate: 'bg-yellow-50 text-yellow-700',
    invalid_record: 'bg-gray-100 text-gray-600',
  };
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cls[category] || cls.invalid_record}`}>{category.replace(/_/g, ' ')}</span>;
}

export function DiscrepanciesPage() {
  const { workspace } = useAuth();
  const qc = useQueryClient();
  const [catFilter, setCatFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('open');
  const [page, setPage] = useState(1);
  const [reviewing, setReviewing] = useState<any>(null);
  const [notes, setNotes] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['discrepancies', workspace?.id, catFilter, statusFilter, page],
    queryFn: () => discrepancies.list(workspace!.id, {
      category: catFilter || undefined,
      status: statusFilter || undefined,
      page,
    }),
    enabled: !!workspace,
  });

  const reviewMut = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      discrepancies.review(workspace!.id, id, action, notes || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['discrepancies', workspace?.id] });
      setReviewing(null);
      setNotes('');
    },
  });

  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-xl font-bold">Discrepancies</h1>
        <p className="text-sm text-gray-500 mt-1">Review and resolve data discrepancies</p>
      </div>

      {/* Filters */}
      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4 mb-4">
        <div className="flex flex-wrap gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Category</label>
            <select value={catFilter} onChange={e => { setCatFilter(e.target.value); setPage(1); }}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm">
              <option value="">All categories</option>
              {CATEGORIES.map(c => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Status</label>
            <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm">
              <option value="">All statuses</option>
              {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
      </div>

      {isLoading && <div className="text-gray-400">Loading…</div>}

      {data?.items && (
        <>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden mb-4">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-100 dark:border-gray-800">
                <tr className="text-left text-gray-500">
                  <th className="px-4 py-3 font-medium">Category</th>
                  <th className="px-4 py-3 font-medium">Explanation</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                  <th className="px-4 py-3 font-medium"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {(data.items as any[]).map((d: any) => (
                  <tr key={d.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                    <td className="px-4 py-3"><CategoryBadge category={d.category} /></td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-400 text-xs max-w-xs truncate">{d.explanation}</td>
                    <td className="px-4 py-3 text-xs text-gray-500">{d.status}</td>
                    <td className="px-4 py-3 text-xs text-gray-500">{new Date(d.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3">
                      {d.status === 'open' && d.category !== 'matched' && (
                        <button onClick={() => setReviewing(d)}
                          className="px-2 py-1 text-xs bg-blue-50 text-blue-700 hover:bg-blue-100 dark:bg-blue-900/20 dark:text-blue-400 rounded-lg">
                          Review
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-sm text-gray-500">
            <span>{data.total} total</span>
            <div className="flex gap-2">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                className="px-3 py-1 border border-gray-300 dark:border-gray-700 rounded-lg disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800">
                Previous
              </button>
              <span className="px-3 py-1">Page {page} of {data.pages || 1}</span>
              <button onClick={() => setPage(p => p + 1)} disabled={page >= (data.pages || 1)}
                className="px-3 py-1 border border-gray-300 dark:border-gray-700 rounded-lg disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800">
                Next
              </button>
            </div>
          </div>
        </>
      )}

      {data?.items?.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <AlertCircle size={40} className="mx-auto mb-3 opacity-30" />
          <p className="font-medium">No discrepancies</p>
          <p className="text-sm mt-1">All clear for the selected filters</p>
        </div>
      )}

      {/* Review modal */}
      {reviewing && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 w-full max-w-md p-6 shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-semibold">Review Discrepancy</h2>
              <button onClick={() => setReviewing(null)}><X size={18} className="text-gray-400" /></button>
            </div>
            <div className="mb-4">
              <CategoryBadge category={reviewing.category} />
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">{reviewing.explanation}</p>
              {reviewing.data_a && (
                <div className="mt-3 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg text-xs font-mono">
                  <div className="text-gray-500 mb-1">Source A:</div>
                  {Object.entries(reviewing.data_a).map(([k, v]: any) => (
                    <div key={k}><span className="text-gray-500">{k}:</span> {String(v)}</div>
                  ))}
                </div>
              )}
              {reviewing.data_b && (
                <div className="mt-2 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg text-xs font-mono">
                  <div className="text-gray-500 mb-1">Source B:</div>
                  {Object.entries(reviewing.data_b).map(([k, v]: any) => (
                    <div key={k}><span className="text-gray-500">{k}:</span> {String(v)}</div>
                  ))}
                </div>
              )}
            </div>
            <textarea value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="Optional notes…"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm h-20 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 mb-4" />
            <div className="flex gap-2">
              <button onClick={() => reviewMut.mutate({ id: reviewing.id, action: 'accept' })}
                disabled={reviewMut.isPending}
                className="flex-1 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-60 text-white rounded-lg text-sm">
                Accept
              </button>
              <button onClick={() => reviewMut.mutate({ id: reviewing.id, action: 'reject' })}
                disabled={reviewMut.isPending}
                className="flex-1 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-60 text-white rounded-lg text-sm">
                Reject
              </button>
              <button onClick={() => reviewMut.mutate({ id: reviewing.id, action: 'resolve' })}
                disabled={reviewMut.isPending}
                className="flex-1 py-2 border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-lg text-sm">
                Resolve
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
