"use client";
import {
  useId,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
} from "react";

export function Brand({ href = "/" }: { href?: string }) {
  return (
    <a className="brand" href={href}>
      <img src="/brand/avishkar-logo.png" alt="" width={34} height={34} />
      avishkar
    </a>
  );
}

export function Field({
  label,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input {...props} id={id} />
    </div>
  );
}

export function Select({
  label,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select {...props} id={id}>
        {children}
      </select>
    </div>
  );
}

export function FormError({ message }: { message: string }) {
  return message ? (
    <p className="form-error" role="alert">
      {message}
    </p>
  ) : null;
}
