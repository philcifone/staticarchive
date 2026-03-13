Neobrutalist Gruvbox Style Guide                                                                 
                                                                                                   
  Color Palette (Gruvbox)                                                                          
                                                                                                   
  Background (light):  #fbf1c7  (--color-neutral-900 in light)
  Background (dark):   #1d2021  (--color-neutral-900 in dark)
  Surface (light):     #282828  (--color-neutral-50 / --color-white)
  Surface (dark):      #282828

  Theme accent colors (set via `data-color-theme` attribute on `<html>`):
    green:   light #98971a  / dark #79740e  (default)
    red:     light #cc241d  / dark #9d0006
    yellow:  light #d79921  / dark #b57614
    blue:    light #458588  / dark #076678
    purple:  light #b16286  / dark #8f3f71
    aqua:    light #689d6a  / dark #427b58
    gray:    light #7c6f64  / dark #3c3836

  CSS variables:
    --color-olive        → current theme accent (light or dark shade)
    --theme-light        → lighter accent shade
    --theme-dark         → darker accent shade

  Fonts

  Display:  'Young Serif', serif     → headings, branding (font-display)
  Body:     'Courier Prime', mono    → everything else (font-sans)

  Card (primary container)

  border-2 border-solid border-neutral-900 dark:border-neutral-100
  bg-white dark:bg-neutral-900
  shadow-[4px_4px_0_0_var(--color-olive)]
  transition-all

  Hover (when interactive):
  hover:translate-x-[2px] hover:translate-y-[2px]
  hover:shadow-[2px_2px_0_0_var(--color-olive)]
  active:translate-x-[2px] active:translate-y-[2px]
  active:shadow-[2px_2px_0_0_var(--color-olive)]

  Button (small interactive element)

  px-3 py-1.5
  border-2 border-neutral-900 dark:border-neutral-100
  bg-neutral-50 dark:bg-neutral-900
  text-neutral-900 dark:text-neutral-100
  font-display
  shadow-[2px_2px_0_0_var(--color-olive)]
  transition-all
  hover:translate-x-[1px] hover:translate-y-[1px]
  hover:shadow-[1px_1px_0_0_var(--color-olive)]
  active:translate-x-[1px] active:translate-y-[1px]
  active:shadow-[1px_1px_0_0_var(--color-olive)]
  cursor-pointer

  Add btn-swipe class for the fill-from-bottom hover animation (desktop only). Pair with
  hover:!text-white dark:hover:!text-white.

  Header / Logo Button (large interactive element)

  px-4 py-2
  border-2 border-neutral-900 dark:border-neutral-100
  bg-white dark:bg-neutral-900
  text-neutral-900 dark:text-neutral-100
  shadow-[3px_3px_0_0_var(--color-olive)]
  transition-all
  hover:translate-x-[1.5px] hover:translate-y-[1.5px]
  hover:shadow-[1.5px_1.5px_0_0_var(--color-olive)]
  font-display

  Tooltip / Popover

  px-3 py-2
  bg-neutral-50 dark:bg-neutral-900
  border-2 border-neutral-900 dark:border-neutral-100
  shadow-[2px_2px_0_0_var(--color-olive)]
  text-neutral-900 dark:text-neutral-100
  text-sm

  Card Top Bar (colored accent strip)

  bg-olive
  px-4 py-2
  border-b-2 border-neutral-900 dark:border-neutral-100

  Sticky Header

  fixed top-0 left-0 right-0
  border-b-4 border-neutral-900 dark:border-neutral-100
  bg-neutral-50/90 dark:bg-neutral-900/90
  backdrop-blur-md
  z-50

  Shadow Scale (by element size)

  ┌────────┬───────────────────────────────────────┬───────────────────────────────────────────┐
  │ Elemen │            Default shadow             │               Hover shadow                │
  │   t    │                                       │                                           │
  ├────────┼───────────────────────────────────────┼───────────────────────────────────────────┤
  │ Card   │ shadow-[4px_4px_0_0_var(--color-olive │ shadow-[2px_2px_0_0_var(--color-olive)]   │
  │        │ )]                                    │                                           │
  ├────────┼───────────────────────────────────────┼───────────────────────────────────────────┤
  │ Logo   │ shadow-[3px_3px_0_0_var(--color-olive │ shadow-[1.5px_1.5px_0_0_var(--color-olive │
  │        │ )]                                    │ )]                                        │
  ├────────┼───────────────────────────────────────┼───────────────────────────────────────────┤
  │ Button │ shadow-[2px_2px_0_0_var(--color-olive │ shadow-[1px_1px_0_0_var(--color-olive)]   │
  │        │ )]                                    │                                           │
  └────────┴───────────────────────────────────────┴───────────────────────────────────────────┘

  Pattern: hover moves element toward shadow by translate-x/y, shadow shrinks by same amount.
  Creates a "press in" effect.

  btn-swipe Animation (CSS)

  Desktop only (@media (hover: hover) and (pointer: fine)): olive-colored ::before pseudo-element
  grows from height: 0% at bottom to 100% on hover, shrinks from top on mouse leave. Mobile:
  instant background-color: var(--color-olive) on :active.

  .btn-swipe {
    position: relative;
    overflow: hidden;
    isolation: isolate;
    z-index: 0;
    border-radius: 0;
  }
  .btn-swipe::before {
    content: '';
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 0%;
    background-color: var(--color-olive);
    z-index: -1;
    transition: height 0.3s ease-in-out;
  }
  .btn-swipe:hover::before {
    height: 100%;
    bottom: 0; top: auto;
  }
  .btn-swipe:not(:hover)::before {
    height: 0%;
    bottom: auto; top: 0;
    transition: height 0.3s ease-in-out;
  }

  Key Rules

  - No border-radius on interactive elements (square corners, neobrutalist)
  - Shadows always use var(--color-olive) (theme-aware accent)
  - All interactive elements need transition-all for smooth press effect
  - Dark mode swaps border colors (neutral-900 ↔ neutral-100) and surface colors
  - Text is always text-neutral-900 dark:text-neutral-100


