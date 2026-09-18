
export type GridSize = 'small' | 'medium' | 'large' | 'huge' | 'gigantic' | 'absurd';

export interface GridSizeOption {
  value: GridSize;
  label: string;
  cardWidth: number;
  maxHeight: number;
  gridMin: number;
  previewSize: number;
}

export const gridSizeOptions: GridSizeOption[] = [
  { value: 'small', label: 'Small', cardWidth: 128, maxHeight: 192, gridMin: 128, previewSize: 360 },
  { value: 'medium', label: 'Medium', cardWidth: 192, maxHeight: 288, gridMin: 176, previewSize: 420 },
  { value: 'large', label: 'Large', cardWidth: 256, maxHeight: 384, gridMin: 240, previewSize: 520 },
  { value: 'huge', label: 'Huge', cardWidth: 340, maxHeight: 510, gridMin: 320, previewSize: 640 },
  { value: 'gigantic', label: 'Gigantic', cardWidth: 460, maxHeight: 690, gridMin: 440, previewSize: 860 },
  { value: 'absurd', label: 'Absurd', cardWidth: 640, maxHeight: 960, gridMin: 600, previewSize: 1120 },
];

/** The thumbnail tier to request for a grid column of ``gridMin`` pixels.
 *
 * The endpoint only serves 300/600/1200 and rejects anything under 300, so a
 * raw ``gridMin`` (128 at Small) would be a 422. Larger columns step up a tier
 * so an Absurd tile is not an upscaled 300px image.
 */
export function thumbnailTierFor(gridMin: number): 300 | 600 | 1200 {
  if (gridMin <= 300) return 300;
  if (gridMin <= 600) return 600;
  return 1200;
}

export const gridSizeByValue = Object.fromEntries(
  gridSizeOptions.map(option => [option.value, option])
) as Record<GridSize, GridSizeOption>;

export function normalizeGridSize(value: unknown): GridSize {
  return gridSizeOptions.some(option => option.value === value) ? value as GridSize : 'medium';
}
