import React, { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../app/AuthContext';
import { datasets, type Dataset } from '../../lib/api';
import { Upload, Plus, Trash2, Eye, Database } from 'lucide-react';

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    completed: 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400',
    failed: 'bg-red-50 text-red-700',
    processing: 'bg-blue-50 text-blue-700',
    pending: 'bg-gray-100 text-gray-600',
  };
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cls[status] || cls.pending}`}>{status}</span>;
}

function CreateDatasetModal({ wsId, onClose }: { wsId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [error, setError] = useState('');
  const mut = useMutation({
    mutationFn: () => datasets.create(wsId, name, desc || undefined),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['datasets', wsId] }); onClose(); },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 w-full max-w-md p-6 shadow-xl">
        <h2 className="text-base font-semibold mb-4">New Dataset</h2>
        {error && <div className="mb-3 p-3 bg-red-50 dark:bg-red-900/20 text-red-700 text-sm rounded-lg">{error}</div>}
        <div className="space-y-3">
          <input placeholder="Dataset name" value={name} onChange={e => setName(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <input placeholder="Description (optional)" value={desc} onChange={e => setDesc(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800">Cancel</button>
          <button onClick={() => mut.mutate()} disabled={!name || mut.isPending}
            className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg">
            {mut.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

function UploadModal({ wsId, dataset, onClose }: { wsId: string; dataset: Dataset; onClose: () => void }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<any>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [step, setStep] = useState<'upload' | 'map' | 'done'>('upload');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true); setError('');
    try {
      const res = await datasets.upload(wsId, dataset.id, file);
      setUploadResult(res);
      // Init mapping with identity
      const m: Record<string, string> = {};
      res.columns.forEach((col: string) => { m[col] = col; });
      setMapping(m);
      setStep('map');
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleImport = async () => {
    setLoading(true); setError('');
    try {
      await datasets.importRows(wsId, dataset.id, mapping);
      qc.invalidateQueries({ queryKey: ['datasets', wsId] });
      setStep('done');
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const CANONICAL = ['reference_id', 'transaction_date', 'amount', 'currency', 'description', 'status', 'customer_reference', 'invoice_id'];

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 w-full max-w-lg p-6 shadow-xl max-h-[90vh] overflow-y-auto">
        <h2 className="text-base font-semibold mb-4">Import File — {dataset.name}</h2>
        {error && <div className="mb-3 p-3 bg-red-50 dark:bg-red-900/20 text-red-700 text-sm rounded-lg">{error}</div>}

        {step === 'upload' && (
          <div className="space-y-4">
            <div className="border-2 border-dashed border-gray-300 dark:border-gray-700 rounded-lg p-8 text-center">
              <Upload size={24} className="mx-auto mb-2 text-gray-400" />
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">Select CSV, XLSX, or JSON file (max 50 MB)</p>
              <input type="file" accept=".csv,.xlsx,.xls,.json" onChange={e => setFile(e.target.files?.[0] || null)}
                className="text-sm" />
            </div>
            {file && <p className="text-sm text-gray-600">Selected: <strong>{file.name}</strong> ({(file.size / 1024).toFixed(1)} KB)</p>}
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800">Cancel</button>
              <button onClick={handleUpload} disabled={!file || loading}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg">
                {loading ? 'Uploading…' : 'Upload & Preview'}
              </button>
            </div>
          </div>
        )}

        {step === 'map' && uploadResult && (
          <div className="space-y-4">
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-sm">
              <strong>{uploadResult.total_rows}</strong> rows detected. {uploadResult.parse_errors?.length > 0 && <span className="text-amber-600"> Warnings: {uploadResult.parse_errors.join(', ')}</span>}
            </div>
            <h3 className="text-sm font-medium">Map source columns to canonical fields</h3>
            <div className="space-y-2">
              {uploadResult.columns.map((col: string) => (
                <div key={col} className="flex items-center gap-2">
                  <span className="flex-1 text-sm font-mono bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">{col}</span>
                  <span className="text-gray-400">→</span>
                  <select value={mapping[col] || ''} onChange={e => setMapping(m => ({ ...m, [col]: e.target.value }))}
                    className="flex-1 px-2 py-1 rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm">
                    <option value="">— skip —</option>
                    {CANONICAL.map(f => <option key={f} value={f}>{f}</option>)}
                    <option value={col}>{col} (keep as-is)</option>
                  </select>
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setStep('upload')} className="px-4 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800">Back</button>
              <button onClick={handleImport} disabled={loading}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg">
                {loading ? 'Importing…' : 'Import'}
              </button>
            </div>
          </div>
        )}

        {step === 'done' && (
          <div className="text-center py-8">
            <div className="text-green-500 text-4xl mb-3">✓</div>
            <p className="font-medium">Import started successfully!</p>
            <p className="text-sm text-gray-500 mt-1">Processing rows in the background. Refresh to see the status.</p>
            <button onClick={onClose} className="mt-4 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700">Close</button>
          </div>
        )}
      </div>
    </div>
  );
}

export function DatasetsPage() {
  const { workspace } = useAuth();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [uploading, setUploading] = useState<Dataset | null>(null);

  const { data: dsList, isLoading } = useQuery({
    queryKey: ['datasets', workspace?.id],
    queryFn: () => datasets.list(workspace!.id),
    enabled: !!workspace,
    refetchInterval: 5000, // Poll for import status
  });

  const deleteMut = useMutation({
    mutationFn: (dsId: string) => datasets.delete(workspace!.id, dsId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['datasets', workspace?.id] }),
  });

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold">Datasets</h1>
          <p className="text-sm text-gray-500 mt-1">Import CSV, XLSX, or JSON files for reconciliation</p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium">
          <Plus size={16} />New Dataset
        </button>
      </div>

      {isLoading && <div className="text-gray-400">Loading…</div>}

      {!isLoading && dsList?.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <Database size={40} className="mx-auto mb-3 opacity-30" />
          <p className="font-medium">No datasets yet</p>
          <p className="text-sm mt-1">Create a dataset and import your data to get started</p>
        </div>
      )}

      {dsList && dsList.length > 0 && (
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100 dark:border-gray-800">
              <tr className="text-left text-gray-500">
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">File</th>
                <th className="px-4 py-3 font-medium">Rows</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Created</th>
                <th className="px-4 py-3 font-medium"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {dsList.map(ds => (
                <tr key={ds.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                  <td className="px-4 py-3 font-medium">{ds.name}</td>
                  <td className="px-4 py-3 text-gray-500 font-mono text-xs">{ds.original_filename || '—'}</td>
                  <td className="px-4 py-3">{ds.row_count}</td>
                  <td className="px-4 py-3"><StatusBadge status={ds.import_status} /></td>
                  <td className="px-4 py-3 text-gray-500">{new Date(ds.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <button onClick={() => setUploading(ds)} className="p-1.5 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded text-blue-600" title="Upload file">
                        <Upload size={14} />
                      </button>
                      <button onClick={() => { if (confirm('Delete this dataset?')) deleteMut.mutate(ds.id); }}
                        className="p-1.5 hover:bg-red-50 dark:hover:bg-red-900/20 rounded text-red-500" title="Delete">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && <CreateDatasetModal wsId={workspace!.id} onClose={() => setShowCreate(false)} />}
      {uploading && <UploadModal wsId={workspace!.id} dataset={uploading} onClose={() => setUploading(null)} />}
    </div>
  );
}
