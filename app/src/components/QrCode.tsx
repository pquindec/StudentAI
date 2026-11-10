/** QR dibujado como SVG a partir de la matriz del backend (negro sobre blanco, con margen). */
export function QrCode({
  rows,
  label,
  className = 'max-w-[18rem]',
}: {
  rows: string[]
  label: string
  className?: string
}) {
  const n = rows.length
  const pad = 4
  const cells: string[] = []
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++)
      if (row[x] === '1') cells.push(`M${x + pad} ${y + pad}h1v1h-1z`)
  })
  return (
    <svg
      viewBox={`0 0 ${n + pad * 2} ${n + pad * 2}`}
      role="img"
      aria-label={label}
      className={`aspect-square w-full rounded-lg ${className}`}
      shapeRendering="crispEdges"
    >
      <rect width="100%" height="100%" fill="#fff" />
      <path d={cells.join('')} fill="#000" />
    </svg>
  )
}
