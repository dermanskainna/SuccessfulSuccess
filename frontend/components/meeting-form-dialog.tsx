"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { CalendarIcon, Loader2, Sparkles, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { Controller, useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { ParticipantsInput } from "@/components/participants-input"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Textarea } from "@/components/ui/textarea"
import { useCreateMeeting, useUpdateMeeting } from "@/hooks/use-meetings"
import { ApiError } from "@/lib/api"
import { getAccessToken } from "@/lib/auth"
import { formatTime, parseIsoDay, toIsoDate, toIsoWithOffset } from "@/lib/datetime"
import type { Meeting } from "@/lib/types"

const AI_PARSER_URL =
  process.env.NEXT_PUBLIC_AI_PARSER_URL ??
  "https://vostb4mxmspex6spovswl5un4m0menfl.lambda-url.us-east-1.on.aws/"

const timePattern = /^([01]\d|2[0-3]):([0-5]\d)$/

const participantSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(120, "Name is too long"),
  email: z
    .string()
    .trim()
    .max(255)
    .refine((value) => value === "" || z.email().safeParse(value).success, {
      message: "Enter a valid email address",
    })
    .optional(),
})

const formSchema = z
  .object({
    name: z.string().trim().min(1, "Name is required").max(200, "Name is too long"),
    description: z.string().trim().max(2000, "Description is too long").optional(),
    location: z.string().trim().max(200, "Location is too long").optional(),
    date: z.date(),
    startTime: z.string().regex(timePattern, "Use HH:mm"),
    endTime: z.string().regex(timePattern, "Use HH:mm"),
    participants: z.array(participantSchema).max(50, "At most 50 participants"),
  })
  .refine((data) => data.endTime > data.startTime, {
    message: "The meeting must end after it starts",
    path: ["endTime"],
  })
  .refine(
    (data) => {
      const keys = data.participants.map(
        (p) => `${p.name.trim().toLowerCase()}|${(p.email ?? "").trim().toLowerCase()}`,
      )
      return new Set(keys).size === keys.length
    },
    { message: "Participants must be unique", path: ["participants"] },
  )

type FormValues = z.infer<typeof formSchema>

type ParticipantErrors = { name?: { message?: string }; email?: { message?: string } }

function participantErrors(rows: unknown): Record<number, string | undefined> {
  if (!Array.isArray(rows)) return {}
  return Object.fromEntries(
    rows.map((row: ParticipantErrors | undefined, index: number) => [
      index,
      row?.name?.message ?? row?.email?.message,
    ]),
  )
}

function defaultValues(meeting?: Meeting): FormValues {
  if (!meeting) {
    return {
      name: "",
      description: "",
      location: "",
      date: new Date(),
      startTime: "10:00",
      endTime: "11:00",
      participants: [{ name: "", email: "" }],
    }
  }
  return {
    name: meeting.name,
    description: meeting.description ?? "",
    location: meeting.location ?? "",
    date: parseIsoDay(meeting.starts_at),
    startTime: formatTime(meeting.starts_at),
    endTime: formatTime(meeting.ends_at),
    participants:
      meeting.participants.length > 0
        ? meeting.participants.map((p) => ({ name: p.name, email: p.email ?? "" }))
        : [{ name: "", email: "" }],
  }
}

export function MeetingFormDialog({
  open,
  onOpenChange,
  meeting,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  meeting?: Meeting
}) {
  const createMeeting = useCreateMeeting()
  const updateMeeting = useUpdateMeeting()
  const [datePickerOpen, setDatePickerOpen] = useState(false)
  const isEdit = !!meeting

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: defaultValues(meeting),
  })

  const {
    register,
    handleSubmit,
    setValue,
    control,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = form

  // ---- Agenda-parsing UI state ----
  const [agendaText, setAgendaText] = useState("")
  const [isParsing, setIsParsing] = useState(false)
  const [suggestedFields, setSuggestedFields] = useState<Set<string>>(new Set())
  const [aiSuggestionMeta, setAiSuggestionMeta] = useState<Record<string, unknown> | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (open) {
      reset(defaultValues(meeting))
      setAgendaText("")
      setIsParsing(false)
      setSuggestedFields(new Set())
      setAiSuggestionMeta(null)
    }
  }, [open, meeting, reset])

  const handleParseAgenda = async () => {
    if (!agendaText.trim()) {
      toast.error("Please paste meeting agenda text first.")
      return
    }

    if (agendaText.length > 10000) {
      toast.error("Agenda text exceeds 10,000 characters limit.")
      return
    }

    const controller = new AbortController()
    abortControllerRef.current = controller
    setIsParsing(true)

    try {
      const token = await getAccessToken()
      const response = await fetch(AI_PARSER_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ text: agendaText }),
        signal: controller.signal,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        throw new Error(errorData?.message || `Failed to parse agenda (${response.status})`)
      }

      const data = await response.json()
      const agenda = data.agenda || data

      const newSuggested = new Set<string>()

      if (agenda.title) {
        setValue("name", agenda.title, { shouldValidate: true })
        newSuggested.add("name")
      }

      // Format description from items and action items if available
      const descParts: string[] = []
      if (agenda.items && agenda.items.length > 0) {
        descParts.push("Agenda Items:")
        agenda.items.forEach((item: { topic: string; owner?: string; minutes?: number }) => {
          let line = `- ${item.topic}`
          if (item.owner) line += ` (${item.owner})`
          if (item.minutes) line += ` [${item.minutes}m]`
          descParts.push(line)
        })
      }
      if (agenda.action_items && agenda.action_items.length > 0) {
        if (descParts.length > 0) descParts.push("")
        descParts.push("Action Items:")
        agenda.action_items.forEach((item: { task: string; owner?: string; due?: string }) => {
          let line = `- [ ] ${item.task}`
          if (item.owner) line += ` (assigned: ${item.owner})`
          if (item.due) line += ` [due: ${item.due}]`
          descParts.push(line)
        })
      }

      if (descParts.length > 0) {
        setValue("description", descParts.join("\n"), { shouldValidate: true })
        newSuggested.add("description")
      }

      if (agenda.location) {
        setValue("location", agenda.location, { shouldValidate: true })
        newSuggested.add("location")
      }

      if (agenda.starts_at) {
        try {
          const startDate = new Date(agenda.starts_at)
          if (!isNaN(startDate.getTime())) {
            setValue("date", startDate, { shouldValidate: true })
            const startH = String(startDate.getHours()).padStart(2, "0")
            const startM = String(startDate.getMinutes()).padStart(2, "0")
            setValue("startTime", `${startH}:${startM}`, { shouldValidate: true })
            newSuggested.add("date")
            newSuggested.add("startTime")

            if (agenda.duration_minutes) {
              const endDate = new Date(startDate.getTime() + agenda.duration_minutes * 60000)
              const endH = String(endDate.getHours()).padStart(2, "0")
              const endM = String(endDate.getMinutes()).padStart(2, "0")
              setValue("endTime", `${endH}:${endM}`, { shouldValidate: true })
              newSuggested.add("endTime")
            }
          }
        } catch {}
      }

      // Collect participants from item owners or action items
      const participantNames = new Set<string>()
      agenda.items?.forEach((i: { owner?: string }) => {
        if (i.owner) participantNames.add(i.owner.trim())
      })
      agenda.action_items?.forEach((i: { owner?: string }) => {
        if (i.owner) participantNames.add(i.owner.trim())
      })

      if (participantNames.size > 0) {
        const parsedParticipants = Array.from(participantNames).map((name) => ({
          name,
          email: "",
        }))
        setValue("participants", parsedParticipants, { shouldValidate: true })
        newSuggested.add("participants")
      }

      setSuggestedFields(newSuggested)
      setAiSuggestionMeta({
        model: data.model,
        prompt_version: data.prompt_version,
        parsed_at: new Date().toISOString(),
      })
      toast.success("Agenda parsed successfully! Fields pre-filled.")
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        toast.info("Agenda parsing cancelled.")
      } else {
        const msg = err instanceof Error ? err.message : "Failed to parse agenda"
        toast.error(msg)
      }
    } finally {
      setIsParsing(false)
      abortControllerRef.current = null
    }
  }

  const handleCancelParse = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
  }

  const onSubmit = handleSubmit(async (values) => {
    const participants = values.participants
      .filter((participant) => participant.name.trim() !== "")
      .map((participant) => ({
        name: participant.name.trim(),
        email: participant.email?.trim() ? participant.email.trim() : null,
      }))

    const payload: Record<string, unknown> = {
      name: values.name.trim(),
      description: values.description?.trim() || null,
      location: values.location?.trim() || null,
      starts_at: toIsoWithOffset(values.date, values.startTime),
      ends_at: toIsoWithOffset(values.date, values.endTime),
      participants,
    }

    if (aiSuggestionMeta) {
      payload.ai_suggestion = aiSuggestionMeta
    }

    try {
      if (meeting) {
        await updateMeeting.mutateAsync({ id: meeting.id, payload: payload as unknown as Meeting })
        toast.success("Meeting updated")
      } else {
        await createMeeting.mutateAsync(payload as unknown as Parameters<typeof createMeeting.mutateAsync>[0])
        toast.success("Meeting created")
      }
      onOpenChange(false)
    } catch (error) {
      if (error instanceof ApiError) {
        const fieldMap: Record<string, keyof FormValues> = {
          name: "name",
          description: "description",
          location: "location",
          starts_at: "startTime",
          ends_at: "endTime",
          participants: "participants",
        }
        for (const detail of error.details) {
          const target = fieldMap[detail.field.split(".")[0] ?? ""]
          if (target) setError(target, { message: detail.message })
        }
        toast.error(error.message)
      } else {
        toast.error(isEdit ? "Could not update the meeting." : "Could not create the meeting.")
      }
    }
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit meeting" : "New meeting"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Change the details, time slot or participants."
              : "Give it a name, a time slot and the people who should be there."}
          </DialogDescription>
        </DialogHeader>

        {/* Paste an Agenda Section */}
        <div className="bg-muted/40 rounded-lg border p-3.5 space-y-2.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="agenda" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <Sparkles className="size-3.5 text-primary" />
              Paste an Agenda (AI Assist)
            </Label>
            {suggestedFields.size > 0 ? (
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4">
                {suggestedFields.size} fields suggested
              </Badge>
            ) : null}
          </div>
          <Textarea
            id="agenda"
            rows={4}
            placeholder="Paste meeting text or agenda here (e.g. 'Project kickoff next Tuesday at 14:00 with Alex, discussing roadmap...')"
            value={agendaText}
            onChange={(e) => setAgendaText(e.target.value)}
            disabled={isParsing}
            className="text-xs resize-none"
          />
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              onClick={handleParseAgenda}
              disabled={isParsing || !agendaText.trim()}
              className="gap-1.5"
            >
              {isParsing ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  Parsing (2-8s)…
                </>
              ) : (
                <>
                  <Sparkles className="size-3.5" />
                  Parse Agenda
                </>
              )}
            </Button>
            {isParsing ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={handleCancelParse}
                className="gap-1 text-xs"
              >
                <X className="size-3.5" />
                Cancel
              </Button>
            ) : null}
          </div>
        </div>

        <form onSubmit={onSubmit} className="space-y-4 pt-1">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="name">Name</Label>
              {suggestedFields.has("name") ? (
                <Badge variant="outline" className="text-[10px] text-primary border-primary/30 h-4 px-1.5">
                  AI suggested
                </Badge>
              ) : null}
            </div>
            <Input
              id="name"
              placeholder="Sprint planning"
              aria-invalid={!!errors.name}
              aria-describedby={errors.name ? "name-error" : undefined}
              {...register("name")}
            />
            {errors.name ? (
              <p id="name-error" className="text-destructive text-sm">
                {errors.name.message}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="description">Description</Label>
              {suggestedFields.has("description") ? (
                <Badge variant="outline" className="text-[10px] text-primary border-primary/30 h-4 px-1.5">
                  AI suggested
                </Badge>
              ) : null}
            </div>
            <Textarea
              id="description"
              rows={3}
              placeholder="What is this meeting about?"
              {...register("description")}
            />
            {errors.description ? (
              <p className="text-destructive text-sm">{errors.description.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="location">Location</Label>
              {suggestedFields.has("location") ? (
                <Badge variant="outline" className="text-[10px] text-primary border-primary/30 h-4 px-1.5">
                  AI suggested
                </Badge>
              ) : null}
            </div>
            <Input id="location" placeholder="Room 3 or a meeting link" {...register("location")} />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2 sm:col-span-1">
              <div className="flex items-center justify-between">
                <Label>Date</Label>
                {suggestedFields.has("date") ? (
                  <Badge variant="outline" className="text-[10px] text-primary border-primary/30 h-4 px-1.5">
                    AI
                  </Badge>
                ) : null}
              </div>
              <Controller
                control={control}
                name="date"
                render={({ field }) => (
                  <Popover open={datePickerOpen} onOpenChange={setDatePickerOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full justify-start font-normal"
                      >
                        <CalendarIcon className="size-4" aria-hidden />
                        {toIsoDate(field.value)}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-0" align="start">
                      <Calendar
                        mode="single"
                        selected={field.value}
                        onSelect={(date) => {
                          if (date) field.onChange(date)
                          setDatePickerOpen(false)
                        }}
                        autoFocus
                      />
                    </PopoverContent>
                  </Popover>
                )}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="startTime">Start</Label>
                {suggestedFields.has("startTime") ? (
                  <Badge variant="outline" className="text-[10px] text-primary border-primary/30 h-4 px-1.5">
                    AI
                  </Badge>
                ) : null}
              </div>
              <Input id="startTime" type="time" step={900} {...register("startTime")} />
              {errors.startTime ? (
                <p className="text-destructive text-sm">{errors.startTime.message}</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="endTime">End</Label>
                {suggestedFields.has("endTime") ? (
                  <Badge variant="outline" className="text-[10px] text-primary border-primary/30 h-4 px-1.5">
                    AI
                  </Badge>
                ) : null}
              </div>
              <Input id="endTime" type="time" step={900} {...register("endTime")} />
              {errors.endTime ? (
                <p className="text-destructive text-sm">{errors.endTime.message}</p>
              ) : null}
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Participants</Label>
              {suggestedFields.has("participants") ? (
                <Badge variant="outline" className="text-[10px] text-primary border-primary/30 h-4 px-1.5">
                  AI suggested
                </Badge>
              ) : null}
            </div>
            <Controller
              control={control}
              name="participants"
              render={({ field }) => (
                <ParticipantsInput
                  value={field.value}
                  onChange={field.onChange}
                  errors={participantErrors(errors.participants)}
                />
              )}
            />
          </div>
          {errors.participants?.message ? (
            <p className="text-destructive text-sm">{errors.participants.message}</p>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isEdit
                ? isSubmitting
                  ? "Saving…"
                  : "Save changes"
                : isSubmitting
                  ? "Creating…"
                  : "Create meeting"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
