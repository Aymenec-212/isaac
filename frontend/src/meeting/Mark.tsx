/** The app mark: nine tesserae, irregular, one loose. Mosaic from fragments. */
export function Mark({ size = 26 }: { size?: number }) {
  const tiles = [
    { x: 0, y: 0, w: 9, h: 9, o: 1 },
    { x: 10, y: 0, w: 5, h: 9, o: 0.75 },
    { x: 16, y: 0, w: 9, h: 5, o: 0.5 },
    { x: 0, y: 10, w: 5, h: 5, o: 0.6 },
    { x: 6, y: 10, w: 9, h: 5, o: 1 },
    { x: 16, y: 6, w: 9, h: 9, o: 0.85 },
    { x: 0, y: 16, w: 9, h: 9, o: 0.45 },
    { x: 10, y: 16, w: 15, h: 4, o: 0.7 },
    { x: 10, y: 21, w: 9, h: 4, o: 1 },
  ];
  return (
    <svg width={size} height={size} viewBox="0 0 25 25" role="img" aria-label="Mosaïque">
      {tiles.map((t, i) => (
        <rect key={i} x={t.x} y={t.y} width={t.w} height={t.h} rx="1" fill="currentColor" opacity={t.o} />
      ))}
    </svg>
  );
}
