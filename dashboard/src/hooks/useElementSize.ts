import {useLayoutEffect, useRef, useState} from 'react';

interface ElementSize {
  width: number;
  height: number;
}

export function useElementSize<T extends HTMLElement>() {
  const elementRef = useRef<T>(null);
  const [size, setSize] = useState<ElementSize>({width: 0, height: 0});

  useLayoutEffect(() => {
    const element = elementRef.current;
    if (!element) {
      return undefined;
    }

    const updateSize = () => {
      const {width, height} = element.getBoundingClientRect();
      setSize((current) =>
        current.width === width && current.height === height ? current : {width, height}
      );
    };

    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  return {elementRef, ...size};
}
