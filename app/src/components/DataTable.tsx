import type { ReactNode } from 'react';
import { motion } from 'framer-motion';

interface DataTableColumn<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  className?: string;
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  data: T[];
  keyExtractor: (row: T) => string;
  rowClassName?: string;
  headerClassName?: string;
  cellClassName?: string;
  emptyMessage?: string;
}

export default function DataTable<T>({
  columns,
  data,
  keyExtractor,
  rowClassName = '',
  headerClassName = '',
  cellClassName = '',
  emptyMessage = 'No data available',
}: DataTableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="panel flex h-32 items-center justify-center">
        <p className="text-sm text-text-muted">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="panel overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className={`border-b border-border-subtle bg-bg-input/50 ${headerClassName}`}>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-2.5 text-left text-2xs font-semibold uppercase tracking-wider text-text-muted ${col.className || ''}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, index) => (
            <motion.tr
              key={keyExtractor(row)}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3, delay: Math.min(index * 0.04, 0.4) }}
              className={`border-b border-border-subtle/60 transition-colors last:border-b-0 hover:bg-bg-elevated/40 ${rowClassName}`}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`px-4 py-3 text-sm ${cellClassName} ${col.className || ''}`}
                >
                  {col.render ? col.render(row) : (row as Record<string, unknown>)[col.key] as ReactNode}
                </td>
              ))}
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
