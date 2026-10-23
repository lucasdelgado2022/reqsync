--
-- PostgreSQL database dump
--

\restrict ShbjViHxMbWNGVIEdsTQIVa0JAkcpXbylTWXXIfvCjvtYSFipB1J5Ay5Eevvg4x

-- Dumped from database version 16.14
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: id_mappings; Type: TABLE; Schema: public; Owner: db_user
--

CREATE TABLE public.id_mappings (
    internalid character varying(255) NOT NULL,
    "3dxid" character varying(255),
    previous_3dxid character varying(255),
    content text,
    object_type character varying(64) NOT NULL,
    active boolean NOT NULL DEFAULT true,
    release_pending boolean NOT NULL DEFAULT false
);


ALTER TABLE public.id_mappings OWNER TO db_user;

--
-- Name: requirement_connections; Type: TABLE; Schema: public; Owner: db_user
--

CREATE TABLE public.requirement_connections (
    id integer NOT NULL,
    child_id character varying(255) NOT NULL,
    parent_id character varying(255) NOT NULL,
    connection_3dx_id character varying(255),
    position integer DEFAULT 0 NOT NULL
);


ALTER TABLE public.requirement_connections OWNER TO db_user;

--
-- Name: object_revision_history; Type: TABLE; Schema: public; Owner: db_user
--

CREATE TABLE public.object_revision_history (
    history_id bigint NOT NULL,
    internalid character varying(255) NOT NULL,
    "3dxid" character varying(255) NOT NULL,
    content text,
    object_type character varying(64) NOT NULL,
    recorded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT object_revision_history_internalid_3dxid_key UNIQUE (internalid, "3dxid")
);

ALTER TABLE public.object_revision_history OWNER TO db_user;

CREATE SEQUENCE public.object_revision_history_history_id_seq
    AS bigint START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.object_revision_history_history_id_seq OWNER TO db_user;
ALTER SEQUENCE public.object_revision_history_history_id_seq
    OWNED BY public.object_revision_history.history_id;
ALTER TABLE ONLY public.object_revision_history
    ALTER COLUMN history_id SET DEFAULT nextval('public.object_revision_history_history_id_seq'::regclass);
ALTER TABLE ONLY public.object_revision_history
    ADD CONSTRAINT object_revision_history_pkey PRIMARY KEY (history_id);
ALTER TABLE ONLY public.object_revision_history
    ADD CONSTRAINT object_revision_history_internalid_fkey
    FOREIGN KEY (internalid) REFERENCES public.id_mappings(internalid);
CREATE INDEX idx_revision_history_3dxid ON public.object_revision_history USING btree ("3dxid");

--
-- Name: connection_history; Type: TABLE; Schema: public; Owner: db_user
--

CREATE TABLE public.connection_history (
    history_id bigint NOT NULL,
    child_id character varying(255) NOT NULL,
    parent_id character varying(255) NOT NULL,
    connection_3dx_id character varying(255),
    recorded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

ALTER TABLE public.connection_history OWNER TO db_user;

CREATE SEQUENCE public.connection_history_history_id_seq
    AS bigint START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.connection_history_history_id_seq OWNER TO db_user;
ALTER SEQUENCE public.connection_history_history_id_seq
    OWNED BY public.connection_history.history_id;
ALTER TABLE ONLY public.connection_history
    ALTER COLUMN history_id SET DEFAULT nextval('public.connection_history_history_id_seq'::regclass);
ALTER TABLE ONLY public.connection_history
    ADD CONSTRAINT connection_history_pkey PRIMARY KEY (history_id);
ALTER TABLE ONLY public.connection_history
    ADD CONSTRAINT connection_history_child_id_fkey
    FOREIGN KEY (child_id) REFERENCES public.id_mappings(internalid);
ALTER TABLE ONLY public.connection_history
    ADD CONSTRAINT connection_history_parent_id_fkey
    FOREIGN KEY (parent_id) REFERENCES public.id_mappings(internalid);
CREATE INDEX idx_connection_history_3dxid ON public.connection_history USING btree (connection_3dx_id);

--
-- Name: requirement_connections_id_seq; Type: SEQUENCE; Schema: public; Owner: db_user
--

CREATE SEQUENCE public.requirement_connections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.requirement_connections_id_seq OWNER TO db_user;

--
-- Name: requirement_connections_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: db_user
--

ALTER SEQUENCE public.requirement_connections_id_seq OWNED BY public.requirement_connections.id;


--
-- Name: requirement_connections id; Type: DEFAULT; Schema: public; Owner: db_user
--

ALTER TABLE ONLY public.requirement_connections ALTER COLUMN id SET DEFAULT nextval('public.requirement_connections_id_seq'::regclass);


--
-- Name: id_mappings id_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: db_user
--

ALTER TABLE ONLY public.id_mappings
    ADD CONSTRAINT id_mappings_pkey PRIMARY KEY (internalid);


--
-- Name: requirement_connections requirement_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: db_user
--

ALTER TABLE ONLY public.requirement_connections
    ADD CONSTRAINT requirement_connections_pkey PRIMARY KEY (id);


--
-- Name: requirement_connections uq_child_parent; Type: CONSTRAINT; Schema: public; Owner: db_user
--

ALTER TABLE ONLY public.requirement_connections
    ADD CONSTRAINT uq_child_parent UNIQUE (child_id, parent_id);


--
-- Name: idx_3dxid; Type: INDEX; Schema: public; Owner: db_user
--

CREATE INDEX idx_3dxid ON public.id_mappings USING btree ("3dxid");


--
-- Name: idx_conn_3dxid; Type: INDEX; Schema: public; Owner: db_user
--

CREATE INDEX idx_conn_3dxid ON public.requirement_connections USING btree (connection_3dx_id);


--
-- Name: idx_conn_child; Type: INDEX; Schema: public; Owner: db_user
--

CREATE INDEX idx_conn_child ON public.requirement_connections USING btree (child_id);


--
-- Name: idx_conn_parent; Type: INDEX; Schema: public; Owner: db_user
--

CREATE INDEX idx_conn_parent ON public.requirement_connections USING btree (parent_id);


--
-- Name: requirement_connections requirement_connections_child_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: db_user
--

ALTER TABLE ONLY public.requirement_connections
    ADD CONSTRAINT requirement_connections_child_id_fkey FOREIGN KEY (child_id) REFERENCES public.id_mappings(internalid) ON DELETE CASCADE;


--
-- Name: requirement_connections requirement_connections_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: db_user
--

ALTER TABLE ONLY public.requirement_connections
    ADD CONSTRAINT requirement_connections_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.id_mappings(internalid) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict ShbjViHxMbWNGVIEdsTQIVa0JAkcpXbylTWXXIfvCjvtYSFipB1J5Ay5Eevvg4x
